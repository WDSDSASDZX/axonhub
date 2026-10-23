from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from axonhub.admin import router as admin_router
from axonhub.config import Settings
from axonhub.db import Database
from axonhub.gateway import router as gateway_router
from axonhub.routing import ChannelRouter


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
    application.state.router = ChannelRouter(
        application.state.settings.failure_threshold,
        application.state.settings.cooldown_seconds,
    )
    application.include_router(admin_router)
    application.include_router(gateway_router)
    web = Path(__file__).with_name("web")
    application.mount("/assets", StaticFiles(directory=web), name="assets")

    @application.get("/", include_in_schema=False)
    async def console():
        return FileResponse(
            web / "index.html",
            headers={
                "Content-Security-Policy": (
                    "default-src 'self'; frame-ancestors 'none'; base-uri 'none'"
                ),
                "Cache-Control": "no-store",
            },
        )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "axonhub-python"}

    return application
