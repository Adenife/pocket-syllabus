from fastapi import APIRouter, HTTPException

from app.schemas.resource import SearchQuery, SearchResponse
from app.services.search_service import SearchService, SearchServiceError

router = APIRouter(tags=["search"])
service = SearchService()


@router.post("/search", response_model=SearchResponse)
def search(payload: SearchQuery) -> SearchResponse:
    try:
        return SearchResponse(query=payload.query, results=service.search(payload.query, payload.limit))
    except SearchServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
