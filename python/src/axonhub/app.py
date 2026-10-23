from contextlib import asynccontextmanager

from fastapi import FastAPI

from axonhub.admin import router as admin_router
from axonhub.config import Settings
from axonhub.db import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.database = Database(app.state.settings.database_url)
        await app.state.database.initialize()
        try:
            yield
        finally:
            await app.state.database.close()

    application = FastAPI(title="AxonHub Python", version="0.1.0", lifespan=lifespan)
    application.state.settings = settings or Settings()
    application.include_router(admin_router)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "axonhub-python"}

    return application
