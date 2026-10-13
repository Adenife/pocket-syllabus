from fastapi import APIRouter
from app.api.v1.endpoints import auth, documents, jobs, search, sync

router = APIRouter()
for module in (auth, documents, jobs, search, sync):
    router.include_router(module.router)
