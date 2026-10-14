"""Portable library archives; never extract archive paths onto the filesystem."""
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from fastapi import HTTPException
from app.schemas.library import PortableMetadata, CategoryCreate

MAX_BUNDLE_BYTES=200*1024*1024

class LibraryBundle:
    def __init__(self,library):
        self.library=library
        self.documents=library.documents

    def export(self,owner,payload):
        identifiers=list(dict.fromkeys(payload.document_ids))
        category=None
        if payload.collection_id:
            category=self.library.category(payload.collection_id,owner,'collection')
            matching=self.library.matching_ids(owner,{'collection_ids':[payload.collection_id]})
            identifiers=[item for item in identifiers if item in matching] if identifiers else matching
        if not identifiers and not category:
            raise HTTPException(400,'Select documents or a collection to export')
        if len(identifiers)>100:
            raise HTTPException(413,'Export at most 100 documents at a time')
        docs=[self.documents.require(identifier,owner) for identifier in identifiers]
        if sum(doc['size'] for doc in docs)>MAX_BUNDLE_BYTES:
            raise HTTPException(413,'Export exceeds 200 MiB')
        stream=tempfile.TemporaryFile()
        try:
            manifest={'format':1,'documents':[], 'collection':{'name':category['name'],'description':category['description']} if category else None}
            with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                for doc in docs:
                    current,data=self.documents.original(doc['id'],owner)
                    if current['content_hash']!=doc['content_hash']:
                        raise HTTPException(409,'A document changed during export; retry')
                    name='documents/'+doc['id']+'/'+doc['filename']
                    archive.writestr(name,data)
                    manifest['documents'].append({'filename':doc['filename'],'path':name,
                        'content_hash':doc['content_hash'],'metadata':self.library.portable(doc)})
                archive.writestr('manifest.json',json.dumps(manifest))
            stream.seek(0)
            return stream
        except BaseException:
            stream.close()
            raise

    def import_archive(self,owner,data):
        import io
        try:
            archive=zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise HTTPException(400,'Invalid library ZIP archive') from exc
        with archive:
            infos=archive.infolist()
            if len(infos)>101 or sum(item.file_size for item in infos)>MAX_BUNDLE_BYTES:
                raise HTTPException(413,'Archive expanded size or file count exceeds limits')
            try:
                manifest=json.loads(archive.read('manifest.json'))
                if manifest.get('format')!=1 or len(manifest['documents'])>100:
                    raise ValueError
                prepared=[];allowed={'manifest.json'}
                for item in manifest['documents']:
                    self.documents.filename(item['filename'])
                    path=item['path']
                    parts=Path(path).parts
                    if len(parts)!=3 or parts[0]!='documents' or parts[-1]!=item['filename'] or any(part in {'.','..'} for part in parts):
                        raise ValueError
                    metadata=PortableMetadata.model_validate(item['metadata'])
                    info=archive.getinfo(path)
                    if info.file_size>self.documents.settings.max_upload_bytes:
                        raise HTTPException(413,'An archived document exceeds the upload limit')
                    content=archive.read(path)
                    self.documents.validate_payload(item['filename'],content)
                    if hashlib.sha256(content).hexdigest()!=item['content_hash']:
                        raise ValueError
                    allowed.add(path);prepared.append((item['filename'],path,metadata))
                    del content
                if set(archive.namelist())!=allowed or len(infos)!=len(allowed):
                    raise ValueError
                collection=manifest.get('collection')
                category_payload=CategoryCreate(kind='collection',**collection) if collection else None
            except HTTPException:
                raise
            except (ValueError,KeyError,TypeError,zipfile.BadZipFile) as exc:
                raise HTTPException(400,'Invalid manifest, unsafe archive path, or content hash mismatch') from exc
            with self.library.db.connect() as conn:
                used,count=conn.execute('SELECT COALESCE(SUM(size),0),COUNT(*) FROM documents WHERE owner_id=? AND purged_at IS NULL',(owner,)).fetchone()
                existing={row[0] for row in conn.execute('SELECT content_hash FROM documents WHERE owner_id=? AND deleted_at IS NULL',(owner,))}
            incoming={}
            for _,path,_ in prepared:
                entry=next(item for item in manifest['documents'] if item['path']==path)
                if entry['content_hash'] not in existing: incoming[entry['content_hash']]=archive.getinfo(path).file_size
            if used+sum(incoming.values())>self.documents.settings.max_library_bytes or count+len(incoming)>self.documents.settings.max_documents:
                raise HTTPException(413,'Import would exceed library quota')
            results=[]
            if category_payload:
                try:
                    self.library.create_category(owner,category_payload)
                except HTTPException as exc:
                    if exc.status_code!=409:
                        raise
            # Content hashes and the whole manifest are validated before writing anything.
            # Upload jobs are independent; retries reuse duplicate originals after interruptions.
            for filename,path,metadata in prepared:
                content=archive.read(path)
                if collection and collection['name'] not in metadata.collections:
                    metadata.collections.append(collection['name'])
                result=self.documents.upload(owner,filename,content)
                doc=result['document']
                self.library.apply_portable(doc['id'],owner,metadata.model_dump(),doc['metadata_version'],merge=result['duplicate'],clone_bookmarks=True)
                results.append({'id':doc['id'],'job_id':result['job_id'],'duplicate':result['duplicate']})
        return {'documents':results,'imported':len(results)}
