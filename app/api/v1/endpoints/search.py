from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.security import current_owner, get_context
from app.schemas.resource import SearchQuery, SearchResponse
from app.services.embedding_service import SearchServiceError

router = APIRouter(tags=['search'])

@router.post('/search', response_model=SearchResponse)
def search(payload: SearchQuery, request: Request, owner: str = Depends(current_owner)):
    context = get_context(request)
    for identifier in payload.document_ids:
        context.documents.require(identifier, owner)
    document_ids=payload.document_ids
    filters={field:getattr(payload,field) for field in ('subject_ids','tag_ids','collection_ids')}
    if any(filters.values()):
        matching=context.library.matching_ids(owner,filters)
        if document_ids:
            matching=[identifier for identifier in matching if identifier in document_ids]
        if not matching:
            return SearchResponse(query=payload.query,results=[])
        document_ids=matching
    try:
        return SearchResponse(query=payload.query, results=context.search.search(
            payload.query, payload.limit, owner, document_ids, payload.hybrid))
    except SearchServiceError as exc:
        raise HTTPException(503, str(exc)) from exc
