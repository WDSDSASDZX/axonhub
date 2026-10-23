from sqlalchemy import select

from axonhub.db import Channel, ClientKey


async def test_admin_requires_credentials(client):
    assert (await client.get("/admin/channels")).status_code == 401


async def test_channel_secrets_are_encrypted_and_never_returned(client, admin_headers):
    body = {
        "name": "Primary",
        "base_url": "https://provider.example/v1/",
        "api_key": "test-upstream-credential",
        "model_map": {"assistant": "upstream-model"},
    }
    response = await client.post("/admin/channels", json=body, headers=admin_headers)
    assert response.status_code == 201
    assert response.json()["base_url"] == "https://provider.example/v1"
    assert "test-upstream-credential" not in response.text
    app = client._transport.app
    async with app.state.database.sessions() as session:
        channel = await session.scalar(select(Channel))
        assert channel.encrypted_key != body["api_key"]


async def test_client_key_is_shown_once_and_can_be_revoked(client, admin_headers):
    response = await client.post("/admin/keys", json={"name": "Laptop"}, headers=admin_headers)
    secret = response.json()["key"]
    response = await client.get("/admin/keys", headers=admin_headers)
    assert secret not in response.text
    async with client._transport.app.state.database.sessions() as session:
        key = await session.scalar(select(ClientKey))
        assert key.key_hash != secret
    assert (await client.delete("/admin/keys/1", headers=admin_headers)).status_code == 204
    assert (await client.get("/admin/keys", headers=admin_headers)).json()[0]["enabled"] is False


async def test_channel_rejects_credentials_in_base_url(client, admin_headers):
    response = await client.post(
        "/admin/channels",
        headers=admin_headers,
        json={
            "name": "Bad URL",
            "base_url": "https://secret@provider.example/v1",
            "api_key": "unused",
            "model_map": {"assistant": "model"},
        },
    )
    assert response.status_code == 422
