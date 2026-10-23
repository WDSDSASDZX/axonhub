import asyncio
import json
import socket
from contextlib import asynccontextmanager

import httpx
import uvicorn
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from axonhub.app import create_app
from axonhub.config import Settings


@asynccontextmanager
async def live_server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_level="error",
            lifespan="on",
            timeout_graceful_shutdown=0.2,
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()


async def test_real_client_disconnect_cancels_upstream_and_persists_log(tmp_path):
    upstream_closed = asyncio.Event()
    upstream = FastAPI()

    @upstream.post("/v1/chat/completions")
    async def completion(request: Request):
        async def chunks():
            try:
                yield 'data: {"choices":[{"delta":{"content":"First"}}]}\n\n'
                while (await request.receive())["type"] != "http.disconnect":
                    pass
            finally:
                upstream_closed.set()

        return StreamingResponse(chunks(), media_type="text/event-stream")

    admin = "live-test-admin-token-at-least-32-characters"
    settings = Settings(
        _env_file=None,
        admin_token=admin,
        encryption_key=Fernet.generate_key().decode(),
        database_url=f"sqlite+aiosqlite:///{tmp_path}/live.db",
    )
    async with live_server(upstream) as provider_url, live_server(create_app(settings)) as url:
        async with httpx.AsyncClient(base_url=url, trust_env=False) as client:
            headers = {"Authorization": "Bearer " + admin}
            response = await client.post(
                "/admin/channels",
                headers=headers,
                json={
                    "name": "Live test",
                    "base_url": provider_url + "/v1",
                    "api_key": "test-only",
                    "model_map": {"assistant": "provider-model"},
                },
            )
            assert response.status_code == 201
            key = (
                await client.post("/admin/keys", headers=headers, json={"name": "Live test"})
            ).json()["key"]
            async with client.stream(
                "POST",
                "/v1/chat/completions",
                headers={"Authorization": "Bearer " + key},
                json={
                    "model": "assistant",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "stream": True,
                },
            ) as stream:
                async for line in stream.aiter_lines():
                    if line.startswith("data:"):
                        assert json.loads(line[5:])["choices"][0]["delta"]["content"] == "First"
                        break
            await asyncio.wait_for(upstream_closed.wait(), 3)
            async with asyncio.timeout(3):
                while True:
                    rows = (await client.get("/admin/requests", headers=headers)).json()["items"]
                    if rows:
                        break
                    await asyncio.sleep(0.01)
            assert rows[0]["status"] == "disconnected"
            assert rows[0]["ttft_ms"] is not None
