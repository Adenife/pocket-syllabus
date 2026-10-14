from pydantic import BaseModel, Field
from app.schemas.job import JobItem

class DocumentItem(BaseModel):
    id: str
    filename: str
    title: str
    content_hash: str
    file_type: str
    size: int
    status: str
    version: int
    indexed_version: int
    warnings: list[str]
    error: str | None
    created_at: float
    updated_at: float
    deleted_at: float | None = None
    display_title: str | None = None
    description: str = ''
    author: str = ''
    publication_year: int | None = None
    edition: str = ''
    material_type: str = 'unspecified'
    favorite: bool = False
    last_opened: float | None = None
    metadata_version: int = 1
    metadata_updated_at: float = 0
    purged_at: float | None = None
    subjects: list[dict] = Field(default_factory=list)
    tags: list[dict] = Field(default_factory=list)
    collections: list[dict] = Field(default_factory=list)
    chunk_count: int = 0
    job: JobItem | None = None

class UploadSession(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    total: int = Field(gt=0)

class UpdateVersion(BaseModel):
    expected_version: int = Field(ge=1)
