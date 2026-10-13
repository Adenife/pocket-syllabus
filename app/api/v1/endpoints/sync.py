from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool
from app.core.security import current_owner, get_context
from app.schemas.document import UploadSession

router = APIRouter(prefix='/sync', tags=['synchronization'])

@router.get('/changes')
def changes(request: Request, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100), owner: str = Depends(current_owner)):
    return get_context(request).sync.changes(owner, after, limit)

@router.post('/uploads', status_code=201)
def create(payload: UploadSession, request: Request, owner: str = Depends(current_owner)):
    return get_context(request).sync.create_upload(owner, payload.filename, payload.total)

@router.get('/uploads/{identifier}')
def status(identifier: str, request: Request, owner: str = Depends(current_owner)):
    return get_context(request).sync.upload_status(identifier, owner)

@router.patch('/uploads/{identifier}')
async def append(identifier: str, request: Request, offset: int = Query(ge=0), owner: str = Depends(current_owner)):
    from fastapi import HTTPException
    data = bytearray()
    async for segment in request.stream():
        data.extend(segment)
        if len(data) > 1024 * 1024:
            raise HTTPException(413, 'Segments must be at most 1 MiB')
    return await run_in_threadpool(get_context(request).sync.append, identifier, owner, offset, bytes(data))

@router.post('/uploads/{identifier}/complete', status_code=202)
def complete(identifier: str, request: Request, document_id: str | None = None,
             expected_version: int | None = Query(None, ge=0), owner: str = Depends(current_owner)):
    return get_context(request).sync.complete(identifier, owner, document_id, expected_version)

@router.delete('/uploads/{identifier}', status_code=204)
def cancel(identifier: str, request: Request, owner: str = Depends(current_owner)):
    get_context(request).sync.cancel(identifier, owner)
    return Response(status_code=204)
