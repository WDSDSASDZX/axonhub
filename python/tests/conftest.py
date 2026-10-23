import httpx
import pytest
from cryptography.fernet import Fernet

from axonhub.app import create_app
from axonhub.config import Settings


@pytest.fixture
def upstream():
    return {"handler": lambda request: httpx.Response(500)}


@pytest.fixture
async def client(tmp_path, upstream):
    settings = Settings(
        _env_file=None,
        admin_token="test-administrator-token-32-characters",
        encryption_key=Fernet.generate_key().decode(),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/gateway.db",
    )
    app = create_app(
        settings,
        upstream_transport=httpx.MockTransport(lambda request: upstream["handler"](request)),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


@pytest.fixture
def admin_headers():
    return {"Authorization": "Bearer test-administrator-token-32-characters"}


@pytest.fixture
async def gateway_headers(client, admin_headers):
    response = await client.post("/admin/keys", json={"name": "Test client"}, headers=admin_headers)
    return {"Authorization": "Bearer " + response.json()["key"]}


@pytest.fixture
async def channel(client, admin_headers):
    response = await client.post(
        "/admin/channels",
        headers=admin_headers,
        json={
            "name": "Primary",
            "base_url": "https://primary.example/v1",
            "api_key": "test-provider-token",
            "model_map": {"assistant": "provider-model"},
        },
    )
    assert response.status_code == 201
    return response.json()
