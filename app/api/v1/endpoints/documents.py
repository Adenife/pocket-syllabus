from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool
from urllib.parse import quote
from app.core.security import current_owner, get_context
from app.schemas.document import DocumentItem

router = APIRouter(prefix='/documents', tags=['documents'])

@router.post('', status_code=202)
async def upload(request: Request, file: UploadFile = File(...),
                 document_id: str | None = None, expected_version: int | None = Query(None, ge=0),
                 expected_metadata_version:int|None=Query(None,ge=1), owner: str = Depends(current_owner)):
    context = get_context(request)
    try:
        data = await file.read(context.settings.max_upload_bytes + 1)
        return await run_in_threadpool(context.documents.upload, owner, file.filename, data, document_id, expected_version, expected_metadata_version=expected_metadata_version)
    finally:
        await file.close()

@router.get('', response_model=list[DocumentItem])
def documents(request: Request, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100), owner: str = Depends(current_owner)):
    return get_context(request).documents.repository.list(owner, offset, limit)

@router.get('/{identifier}', response_model=DocumentItem)
def document(identifier: str, request: Request, owner: str = Depends(current_owner)):
    return get_context(request).documents.require(identifier, owner)

@router.delete('/{identifier}', status_code=204)
def delete(identifier: str, request: Request, expected_version: int | None = Query(None, ge=1), owner: str = Depends(current_owner)):
    get_context(request).documents.delete(identifier, owner, expected_version)
    return Response(status_code=204)

@router.post('/{identifier}/reindex', status_code=202)
def reindex(identifier: str, request: Request, owner: str = Depends(current_owner)):
    return {'job_id': get_context(request).documents.reindex(identifier, owner)}

@router.get('/{identifier}/original')
def original(identifier: str, request: Request, include_trash:bool=False,track_open:bool=True,owner: str = Depends(current_owner)):
    doc, data = get_context(request).documents.original(identifier, owner,include_trash)
    if not include_trash and track_open: get_context(request).library.opened(identifier,owner)
    headers = {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(doc['filename']),
               'Accept-Ranges': 'bytes', 'ETag': '"' + doc['content_hash'] + '"'}
    range_value = request.headers.get('range')
    if range_value and request.headers.get('if-range', headers['ETag']) == headers['ETag']:
        import re
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_value)
        if not match or not any(match.groups()):
            raise HTTPException(416, 'Invalid byte range', headers={'Content-Range': f'bytes */{len(data)}'})
        start = int(match[1]) if match[1] else max(0, len(data) - int(match[2]))
        end = min(int(match[2]), len(data) - 1) if match[1] and match[2] else len(data) - 1
        if start > end or start >= len(data):
            raise HTTPException(416, 'Unsatisfiable byte range', headers={'Content-Range': f'bytes */{len(data)}'})
        headers['Content-Range'] = f'bytes {start}-{end}/{len(data)}'
        return Response(data[start:end + 1], status_code=206, media_type='application/octet-stream', headers=headers)
    return Response(data, media_type='application/octet-stream', headers=headers)
