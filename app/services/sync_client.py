"""Two-way original-file synchronization with checkpoints and conflict detection."""
import hashlib
import json
import os
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
        response = self.request('GET', f"/documents/{doc['id']}/original", stream=True,
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
                              params={'document_id': doc['id'], 'expected_version': expected}).json()
        transfers.pop(key, None)
        save()
        return result['document']

    def delete(self, doc):
        self.request('DELETE', '/documents/' + doc['id'], params={'expected_version': doc['version']})


def signature(doc):
    if not doc:
        return None
    return 'deleted' if doc['deleted_at'] is not None else doc['content_hash']


class SyncClient:
    def __init__(self, local, remote, state_path):
        self.local, self.remote = local, remote
        self.path = Path(state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {'pairs': {}, 'transfers': {}}
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
        left, right = self.local.manifest(), self.remote.manifest()
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
                if destination and destination['deleted_at'] is None:
                    target.delete(destination)
                self.state['pairs'][identifier] = {'local': 'deleted' if local else None, 'remote': 'deleted' if remote else None}
            elif source:
                if destination and destination['deleted_at'] is not None:
                    conflicts.append(identifier)
                    continue
                path = origin.download(source, self.path.parent / 'sync-downloads')
                target.upload(source, path, destination, self.state['transfers'], self.save)
                path.unlink(missing_ok=True)
                self.state['pairs'][identifier] = {'local': source['content_hash'], 'remote': source['content_hash']}
            transferred += 1
            self.save()
        self.save()
        return {'transferred': transferred, 'conflicts': conflicts}
