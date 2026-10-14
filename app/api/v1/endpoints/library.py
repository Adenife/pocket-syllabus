from typing import Annotated
from fastapi import APIRouter,Depends,File,HTTPException,Query,Request,Response,UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from app.core.security import current_owner,get_context
from app.schemas.library import (LibraryFilters,CategoryCreate,CategoryEdit,MetadataPatch,
    BulkAction,BookmarkCreate,BookmarkEdit,ExportRequest,PortablePatch)
from app.services.library_bundle import LibraryBundle

router=APIRouter(prefix='/library',tags=['library'])

@router.get('/documents')
def listing(request:Request,filters:Annotated[LibraryFilters,Query()],owner:str=Depends(current_owner)):
    return get_context(request).library.list(owner,filters.model_dump())

@router.get('/catalog')
def catalog(request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.catalog(owner)

@router.post('/categories',status_code=201)
def create(payload:CategoryCreate,request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.create_category(owner,payload)

@router.patch('/categories/{identifier}')
def rename(identifier:str,payload:CategoryEdit,request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.change_category(identifier,owner,payload)

@router.delete('/categories/{identifier}',status_code=204)
def remove(identifier:str,request:Request,expected_name:str|None=None,expected_description:str|None=None,require_empty:bool=False,owner:str=Depends(current_owner)):
    get_context(request).library.change_category(identifier,owner,expected_name=expected_name,expected_description=expected_description,require_empty=require_empty)
    return Response(status_code=204)

@router.patch('/documents/{identifier}')
def metadata(identifier:str,payload:MetadataPatch,request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.patch(identifier,owner,payload)

@router.put('/documents/{identifier}/organization')
def organization(identifier:str,payload:PortablePatch,request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.apply_portable(identifier,owner,payload.model_dump(exclude={'expected_metadata_version'}),payload.expected_metadata_version)

@router.post('/bulk')
def bulk(payload:BulkAction,request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.bulk(owner,payload)

@router.get('/statistics')
def statistics(request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.statistics(owner)

@router.get('/duplicates')
def duplicates(request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.duplicates(owner)

@router.post('/documents/{identifier}/trash')
def trash(identifier:str,request:Request,expected_version:int|None=Query(None,ge=1),owner:str=Depends(current_owner)):
    return get_context(request).documents.trash(identifier,owner,expected_version)

@router.post('/documents/{identifier}/restore')
def restore(identifier:str,request:Request,expected_version:int|None=Query(None,ge=1),owner:str=Depends(current_owner)):
    return get_context(request).documents.restore(identifier,owner,expected_version)

@router.post('/documents/{identifier}/opened')
def opened(identifier:str,request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.opened(identifier,owner)

@router.get('/documents/{identifier}/preview')
def preview(identifier:str,request:Request,offset:int=Query(0,ge=0),limit:int=Query(10,ge=1,le=20),page:int|None=Query(None,ge=1),owner:str=Depends(current_owner)):
    return get_context(request).library.preview(identifier,owner,offset,limit,page)

@router.get('/documents/{identifier}/suggestions')
def suggestions(identifier:str,request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.suggestions(identifier,owner)

@router.get('/documents/{identifier}/related')
def related(identifier:str,request:Request,limit:int=Query(5,ge=1,le=10),owner:str=Depends(current_owner)):
    from app.services.embedding_service import SearchServiceError
    try:
        return get_context(request).library.related(identifier,owner,limit)
    except SearchServiceError as exc:
        raise HTTPException(503,str(exc)) from exc

@router.get('/bookmarks')
def bookmarks(request:Request,document_id:str|None=None,offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=100),owner:str=Depends(current_owner)):
    return get_context(request).library.bookmarks(owner,document_id,offset,limit)

@router.post('/bookmarks',status_code=201)
def bookmark(payload:BookmarkCreate,request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.create_bookmark(owner,payload)

@router.patch('/bookmarks/{identifier}')
def annotate(identifier:str,payload:BookmarkEdit,request:Request,owner:str=Depends(current_owner)):
    return get_context(request).library.edit_bookmark(identifier,owner,payload.annotation)

@router.delete('/bookmarks/{identifier}',status_code=204)
def delete_bookmark(identifier:str,request:Request,owner:str=Depends(current_owner)):
    get_context(request).library.edit_bookmark(identifier,owner)
    return Response(status_code=204)

@router.post('/export')
def export(payload:ExportRequest,request:Request,owner:str=Depends(current_owner)):
    stream=LibraryBundle(get_context(request).library).export(owner,payload)
    def chunks():
        try:
            while block:=stream.read(65536):
                yield block
        finally:
            stream.close()
    return StreamingResponse(chunks(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="pocket-library.zip"'})

@router.post('/import',status_code=202)
async def import_bundle(request:Request,file:UploadFile=File(...),owner:str=Depends(current_owner)):
    context=get_context(request)
    try:
        data=await file.read(context.settings.max_upload_bytes+1)
        if len(data)>context.settings.max_upload_bytes:
            raise HTTPException(413,'Archive exceeds upload limit')
        return await run_in_threadpool(LibraryBundle(context.library).import_archive,owner,data)
    finally:
        await file.close()
