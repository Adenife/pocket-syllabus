from fastapi import FastAPI
from app.api import router as api_router

app = FastAPI(title="PocketSyllabus", version="1.0.0", description="Local OER discovery")
app.include_router(api_router, prefix="/api")


@app.get("/")
def health_check() -> dict[str, str]:
    return {"status": "ok", "app": "PocketSyllabus"}
