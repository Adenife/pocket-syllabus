from pydantic import BaseModel

class JobItem(BaseModel):
    id: str
    document_id: str
    status: str
    stage: str
    progress: int
    chunks: int
    error: str | None
    attempts: int
