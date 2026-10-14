"""Two-way original-file synchronization with checkpoints and conflict detection."""
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse
import requests

class Peer:
    def __init__(self, url, token=''):
        parsed = urlparse(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('Use an HTTP(S) API URL without embedded credentials')
        if parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError('Remote synchronization requires HTTPS')
        self.url = url.rstrip('/')
        self.session = requests.Session()
        if token:
            self.session.headers['Authorization'] = 'Bearer ' + token

    def request(self, method, path, **kwargs):
        response = self.session.request(method, self.url + path, timeout=120, allow_redirects=False, **kwargs)
        if 300 <= response.status_code < 400:
            raise ValueError('Synchronization redirects are not allowed; use the final HTTPS API address')
        response.raise_for_status()
        return response

    def catalog(self):
        result=self.request('GET','/library/catalog').json()
        return [item for items in result.values() for item in items]

    def create_category(self,item):
        result=self.request('POST','/library/categories',json={key:item.get(key,'') for key in ('kind','name','description')}).json()
        return {**result,'document_count':0,'membership_count':0}

    def update_category(self,target,source):
        result=self.request('PATCH','/library/categories/'+target['id'],json={
            'name':source['name'],'description':source.get('description',''),
            'expected_name':target['name'],'expected_description':target.get('description','')}).json()
        return {**result,'document_count':target.get('document_count',0),'membership_count':target.get('membership_count',0)}

    def delete_category(self,item):
        self.request('DELETE','/library/categories/'+item['id'],params={'expected_name':item['name'],
            'expected_description':item.get('description',''),'require_empty':True})

    def manifest_cached(self,cache):
        identity=self.request('GET','/sync/identity').json()
        key=[identity['library_id'],identity['owner_id']]
        if cache.get('identity',key)!=key:
            raise ValueError('Checkpoint belongs to a different account or library; use a new state file')
        if cache.get('cursor',0)>identity['latest_sequence']:
            raise ValueError('Library history was rolled back; review it with a fresh checkpoint')
        docs=cache.setdefault('documents',{})
        cursor=cache.get('cursor',0)
        while True:
            result=self.request('GET','/sync/changes',params={'after':cursor}).json()
            for change in result['changes']:
                docs[change['document']['id']]=change['document']
            cursor=result['cursor']
            if not result['has_more']: break
        cache.update(identity=key,cursor=cursor)
        return dict(docs)

    def manifest(self):
        docs, cursor = {}, 0
        while True:
            result = self.request('GET', '/sync/changes', params={'after': cursor}).json()
            for change in result['changes']:
                docs[change['document']['id']] = change['document']
            cursor = result['cursor']
            if not result['has_more']:
                return docs

    def download(self, doc, folder):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (doc['id'] + '-' + doc['content_hash'] + '.part')
        offset = path.stat().st_size if path.exists() else 0
        if offset >= doc['size'] and path.exists():
            if offset == doc['size'] and hashlib.sha256(path.read_bytes()).hexdigest() == doc['content_hash']:
                return path
            path.unlink()
            offset = 0
        response = self.request('GET', f"/documents/{doc['id']}/original", stream=True,params={'include_trash':doc['deleted_at'] is not None,'track_open':False},
            headers={'Range': f'bytes={offset}-', 'If-Range': '"' + doc['content_hash'] + '"'} if offset else {})
        with response, path.open('ab' if offset and response.status_code == 206 else 'wb') as stream:
            path.chmod(0o600)
            for data in response.iter_content(64 * 1024):
                stream.write(data)
        if path.stat().st_size != doc['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != doc['content_hash']:
            path.unlink(missing_ok=True)
            raise ValueError('Downloaded file failed its content hash check')
        return path

    def upload(self, doc, path, destination, transfers, save):
        key = self.url + ':' + doc['id']
        transfer = transfers.get(key)
        if transfer and transfer['hash'] != doc['content_hash']:
            self.request('DELETE', '/sync/uploads/' + transfer['session'])
            transfers.pop(key, None)
            transfer = None
        if transfer:
            response = self.session.get(self.url + '/sync/uploads/' + transfer['session'], timeout=120, allow_redirects=False)
            if response.status_code == 404:
                transfer = None
            else:
                response.raise_for_status()
                session = response.json()
        if not transfer:
            session = self.request('POST', '/sync/uploads', json={'filename': doc['filename'], 'total': doc['size']}).json()
            transfer = {'session': session['id'], 'hash': doc['content_hash']}
            transfers[key] = transfer
            save()
        with path.open('rb') as stream:
            stream.seek(session['offset'])
            offset = session['offset']
            while data := stream.read(1024 * 1024):
                session = self.request('PATCH', '/sync/uploads/' + transfer['session'], params={'offset': offset}, data=data,
                                       headers={'Content-Type': 'application/octet-stream'}).json()
                offset = session['offset']
        expected = destination['version'] if destination else 0
        result = self.request('POST', '/sync/uploads/' + transfer['session'] + '/complete',
                              params={'document_id': doc['id'], 'expected_version': expected,
                                      'expected_metadata_version':destination['metadata_version'] if destination else 1,
                                      'preserve_trash':bool(destination and destination['deleted_at'] is not None)}).json()
        updated=result['document']
        self.organization(doc,updated,expected_metadata_version=destination['metadata_version'] if destination else 1)
        transfers.pop(key, None)
        save()
        return updated

    def organization(self,source,destination,expected_metadata_version=None):
        if 'organization' in source:
            self.request('PUT','/library/documents/'+source['id']+'/organization',
                json={**source['organization'],'expected_metadata_version':expected_metadata_version or destination['metadata_version']})

    def delete(self,doc,purge=False):
        self.request('DELETE' if purge else 'POST',
            '/documents/'+doc['id'] if purge else '/library/documents/'+doc['id']+'/trash',
            params={'expected_version':doc['version']})

    def tombstone(self,doc):
        self.request('POST','/sync/tombstones/'+doc['id'])

    def restore(self,doc):
        self.request('POST','/library/documents/'+doc['id']+'/restore',params={'expected_version':doc['version']})
        return self.manifest()[doc['id']]

    def wait_indexing(self,identifier):
        deadline=time.monotonic()+120
        while True:
            doc=self.request('GET','/documents/'+identifier).json()
            if doc['status'] not in {'queued','indexing'}:
                return doc
            if time.monotonic()>deadline:
                raise ValueError('Wait for restored document indexing to finish, then retry synchronization')
            time.sleep(0.5)


def signature(doc):
    if not doc:
        return None
    if doc.get('purged_at') is not None:
        return 'purged'
    organization=dict(doc.get('organization') or {field:doc.get(field) for field in
        ['display_title','description','author','publication_year','edition','material_type','favorite']})
    if 'display_title' in organization:
        organization['title']=organization.pop('display_title')
    for field in ['subjects','tags','collections']:
        names=organization.get(field,[item['name'] for item in doc.get(field,[])])
        organization[field]=sorted(name.casefold() for name in names)
    value={'hash':doc['content_hash'],'trash':doc['deleted_at'] is not None,'organization':organization}
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


class SyncClient:
    def __init__(self, local, remote, state_path):
        self.local, self.remote = local, remote
        self.path = Path(state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {'format':2,'pairs': {}, 'transfers': {}}
        if self.state.get('format')!=2:
            raise ValueError('Checkpoint predates organization sync; use a new --state-file')
        peer_pair = [local.url, remote.url]
        if self.state.get('peers', peer_pair) != peer_pair:
            raise ValueError('Use a separate checkpoint file for each peer pair')
        self.state['peers'] = peer_pair

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, indent=2))
        temporary.chmod(0o600)
        os.replace(temporary, self.path)

    def run(self):
        caches=self.state.setdefault('manifests',{})
        left=self.local.manifest_cached(caches.setdefault('local',{})) if hasattr(self.local,'manifest_cached') else self.local.manifest()
        right=self.remote.manifest_cached(caches.setdefault('remote',{})) if hasattr(self.remote,'manifest_cached') else self.remote.manifest()
        catalogs=(self.local.catalog(),self.remote.catalog()) if hasattr(self.local,'catalog') and hasattr(self.remote,'catalog') else None
        conflicts, transferred = [], 0
        for identifier in sorted(set(left) | set(right)):
            local, remote = left.get(identifier), right.get(identifier)
            ls, rs = signature(local), signature(remote)
            baseline = self.state['pairs'].get(identifier)
            if ls == rs:
                self.state['pairs'][identifier] = {'local': ls, 'remote': rs}
                continue
            lc = ls != (baseline['local'] if baseline else None)
            rc = rs != (baseline['remote'] if baseline else None)
            if lc and rc:
                conflicts.append(identifier)
                continue
            if not lc and not rc:
                continue
            source, destination, origin, target = (local, remote, self.local, self.remote) if lc else (remote, local, self.remote, self.local)
            if source and source['deleted_at'] is not None:
                purge=source.get('purged_at') is not None
                if purge:
                    if destination and destination.get('purged_at') is None:
                        target.delete(destination,purge=True)
                    elif not destination:
                        target.tombstone(source)
                else:
                    # Trash is recoverable: replicate the latest original before hiding it.
                    if destination and destination.get('purged_at') is not None:
                        conflicts.append(identifier);continue
                    if not destination or destination['content_hash']!=source['content_hash']:
                        if destination and destination['status'] in {'queued','indexing'}:
                            destination=target.wait_indexing(identifier)
                        path=origin.download(source,self.path.parent/'sync-downloads')
                        target.upload(source,path,destination,self.state['transfers'],self.save)
                        path.unlink(missing_ok=True)
                        destination=target.manifest()[identifier]
                    if destination['deleted_at'] is None:
                        target.delete(destination,purge=False)
                    destination=target.manifest()[identifier]
                    target.organization(source,destination)
                refreshed=target.manifest().get(identifier)
                self.state['pairs'][identifier]={'local':signature(source if lc else refreshed),
                                                 'remote':signature(refreshed if lc else source)}
            elif source:
                if destination and destination.get('purged_at') is not None:
                    conflicts.append(identifier)
                    continue
                if destination and destination['deleted_at'] is not None:
                    destination=target.restore(destination)
                    baseline=baseline or {'local':None,'remote':None}
                    baseline['remote' if lc else 'local']=signature(destination)
                    self.state['pairs'][identifier]=baseline
                    self.save()
                if destination and destination['content_hash']==source['content_hash']:
                    target.organization(source,destination)
                else:
                    if destination and destination['status'] in {'queued','indexing'}:
                        destination=target.wait_indexing(identifier)
                    path=origin.download(source,self.path.parent/'sync-downloads')
                    target.upload(source,path,destination,self.state['transfers'],self.save)
                    path.unlink(missing_ok=True)
                self.state['pairs'][identifier]={'local':signature(source),'remote':signature(source)}
            transferred += 1
            self.save()
        self.save()
        catalog_changes=0
        if catalogs is not None:
            from app.services.catalog_sync import synchronize
            catalog_changes,catalog_conflicts=synchronize(self.local,self.remote,self.state,*catalogs)
            conflicts.extend(catalog_conflicts)
            self.save()
        return {'transferred': transferred,'catalog_changes':catalog_changes, 'conflicts': conflicts}
