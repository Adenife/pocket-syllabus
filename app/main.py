from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from app.api import router as api_router
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.middleware import RequestControls
from app.services.context import Context


def create_app(settings=None, context=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        app.state.context = context or Context(settings)
        if settings.worker_enabled:
            app.state.context.worker.start()
        yield
        app.state.context.worker.close()

    app = FastAPI(title='PocketSyllabus', version='2.0.0', lifespan=lifespan)
    if context:
        app.state.context = context
    app.include_router(api_router, prefix='/api')
    app.add_middleware(RequestControls,settings=settings)

    @app.get('/')
    def health_check():
        return {'status':'ok','app':'PocketSyllabus'}

    @app.get('/ready')
    def readiness(request: Request):
        with request.app.state.context.db.connect() as conn:
            conn.execute('SELECT 1').fetchone()
        return {'status':'ready'}

    return app

app = create_app()
