from pydantic import BaseModel, Field, field_validator


class SearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=3, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Query must contain non-whitespace characters")
        return value


class SearchResultItem(BaseModel):
    id: int
    source_title: str
    section: str
    text_excerpt: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
