from pydantic import BaseModel, Field, field_validator

class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r'^[a-zA-Z0-9_.-]+$')
    password: str = Field(min_length=10, max_length=128)

    @field_validator('username')
    @classmethod
    def normalize(cls, value):
        return value.lower()
