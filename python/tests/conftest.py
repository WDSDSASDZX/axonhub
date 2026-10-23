import httpx
import pytest
from cryptography.fernet import Fernet

from axonhub.app import create_app
from axonhub.config import Settings


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        _env_file=None,
        admin_token="test-administrator-token-32-characters",
        encryption_key=Fernet.generate_key().decode(),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gateway.db",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


@pytest.fixture
def admin_headers():
    return {"Authorization": "Bearer test-administrator-token-32-characters"}
