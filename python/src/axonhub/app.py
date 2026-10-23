from fastapi import FastAPI

from axonhub.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    application = FastAPI(title="AxonHub Python", version="0.1.0")
    application.state.settings = settings or Settings()

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "axonhub-python"}

    return application
