from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from axonhub.admin import router as admin_router
from axonhub.config import Settings
from axonhub.db import Database
from axonhub.gateway import router as gateway_router


def create_app(
    settings: Settings | None = None,
    *,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.database = Database(app.state.settings.database_url)
        await app.state.database.initialize()
        app.state.upstream = httpx.AsyncClient(
            transport=upstream_transport,
            timeout=httpx.Timeout(
                app.state.settings.read_timeout, connect=app.state.settings.connect_timeout
            ),
            follow_redirects=False,
            trust_env=False,
        )
        try:
            yield
        finally:
            await app.state.upstream.aclose()
            await app.state.database.close()

    application = FastAPI(title="AxonHub Python", version="0.1.0", lifespan=lifespan)
    application.state.settings = settings or Settings()
    application.include_router(admin_router)
    application.include_router(gateway_router)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "axonhub-python"}

    return application
