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
    try:
        return SearchResponse(query=payload.query, results=context.search.search(
            payload.query, payload.limit, owner, payload.document_ids, payload.hybrid))
    except SearchServiceError as exc:
        raise HTTPException(503, str(exc)) from exc
