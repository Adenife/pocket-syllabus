from pydantic import BaseModel, Field, field_validator

class SearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=3, ge=1, le=50)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    hybrid: bool = True

    @field_validator('query')
    @classmethod
    def strip_query(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Query must contain non-whitespace characters')
        return value

class SearchResultItem(BaseModel):
    id: int
    document_id: str
    source_title: str
    section: str
    text_excerpt: str
    score: float
    page: int | None = None
    line: int | None = None
    filename: str

class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
