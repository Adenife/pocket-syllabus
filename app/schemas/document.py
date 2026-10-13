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
    chunk_count: int = 0
    job: JobItem | None = None

class UploadSession(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    total: int = Field(gt=0)

class UpdateVersion(BaseModel):
    expected_version: int = Field(ge=1)
