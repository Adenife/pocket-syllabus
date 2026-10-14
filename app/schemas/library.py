from typing import Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict

Kind = Literal['subject','tag','collection']
MaterialType = Literal['unspecified','textbook','lecture_notes','syllabus','assignment','revision_notes','other']

class CategoryCreate(BaseModel):
    kind: Kind
    name: str = Field(min_length=1,max_length=80)
    description: str = Field(default='',max_length=1000)
    @field_validator('name')
    @classmethod
    def clean(cls,value):
        value=value.strip()
        if not value:
            raise ValueError('Name cannot be blank')
        return value

class CategoryEdit(BaseModel):
    expected_name: str | None = None
    expected_description: str | None = None
    name: str = Field(min_length=1,max_length=80)
    description: str = Field(default='',max_length=1000)
    @field_validator('name')
    @classmethod
    def clean(cls,value):
        return CategoryCreate.clean(value)

class MetadataPatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_metadata_version: int = Field(ge=1)
    title: str | None = Field(default=None,min_length=1,max_length=256)
    description: str | None = Field(default=None,max_length=4000)
    author: str | None = Field(default=None,max_length=256)
    publication_year: int | None = Field(default=None,ge=1000,le=9999)
    edition: str | None = Field(default=None,max_length=80)
    material_type: MaterialType | None = None
    favorite: bool | None = None
    subject_ids: list[str] | None = Field(default=None,max_length=30)
    tag_ids: list[str] | None = Field(default=None,max_length=50)
    collection_ids: list[str] | None = Field(default=None,max_length=30)
    @field_validator('title')
    @classmethod
    def title_not_blank(cls,value):
        if value is not None and not value.strip():
            raise ValueError('Title cannot be blank')
        return value.strip() if value else value

class LibraryFilters(BaseModel):
    q: str = Field(default='',max_length=256)
    subject_ids: list[str] = Field(default_factory=list,max_length=30)
    tag_ids: list[str] = Field(default_factory=list,max_length=50)
    collection_ids: list[str] = Field(default_factory=list,max_length=30)
    material_type: MaterialType | None = None
    status: Literal['ready','queued','indexing','failed'] | None = None
    file_type: Literal['.pdf','.docx','.md','.txt'] | None = None
    favorite: bool | None = None
    trash: bool = False
    sort_by: Literal['title','created_at','updated_at','size','status','last_opened','author','publication_year'] = 'created_at'
    sort_order: Literal['asc','desc'] = 'desc'
    offset: int = Field(default=0,ge=0)
    limit: int = Field(default=20,ge=1,le=100)

class BulkAction(BaseModel):
    document_ids: list[str] = Field(min_length=1,max_length=100)
    action: Literal['assign','remove','favorite','reindex','trash','restore']
    category_ids: list[str] = Field(default_factory=list,max_length=50)
    favorite: bool = True
    expected_metadata_versions: dict[str,int] = Field(default_factory=dict,max_length=100)

class BookmarkCreate(BaseModel):
    chunk_id: int
    annotation: str = Field(default='',max_length=4000)

class BookmarkEdit(BaseModel):
    annotation: str = Field(max_length=4000)

class ExportRequest(BaseModel):
    document_ids: list[str] = Field(default_factory=list,max_length=100)
    collection_id: str | None = None

class PortableBookmark(BaseModel):
    id: str
    excerpt: str = Field(max_length=10000)
    annotation: str = Field(default='',max_length=4000)
    section: str = Field(max_length=1024)
    page: int | None = Field(default=None,ge=1)
    line: int | None = Field(default=None,ge=1)
    document_version: int = Field(ge=0)
    @field_validator('id')
    @classmethod
    def valid_uuid(cls,value):
        import uuid
        return str(uuid.UUID(value))

class PortableMetadata(BaseModel):
    title: str | None = Field(default=None,max_length=256)
    description: str = Field(default='',max_length=4000)
    author: str = Field(default='',max_length=256)
    publication_year: int | None = Field(default=None,ge=1000,le=9999)
    edition: str = Field(default='',max_length=80)
    material_type: MaterialType = 'unspecified'
    favorite: bool = False
    bookmarks: list[PortableBookmark] = Field(default_factory=list,max_length=100)
    subjects: list[str] = Field(default_factory=list,max_length=30)
    tags: list[str] = Field(default_factory=list,max_length=50)
    collections: list[str] = Field(default_factory=list,max_length=30)
    @field_validator('subjects','tags','collections')
    @classmethod
    def valid_names(cls,names):
        if any(not name.strip() or len(name)>80 for name in names):
            raise ValueError('Category names must contain 1–80 characters')
        return list(dict.fromkeys(name.strip() for name in names))

class PortablePatch(PortableMetadata):
    expected_metadata_version: int = Field(ge=1)
