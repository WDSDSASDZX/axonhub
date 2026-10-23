import asyncio
from collections import Counter
from types import SimpleNamespace

import httpx
import pytest

from axonhub.gateway import stream_events
from axonhub.routing import ChannelRouter
from axonhub.telemetry import RequestTrace

BODY = {"model": "assistant", "messages": [{"role": "user", "content": "Hello"}]}


@pytest.fixture
async def backup(client, admin_headers):
    response = await client.post(
        "/admin/channels",
        headers=admin_headers,
        json={
            "name": "Backup",
            "base_url": "https://backup.example/v1",
            "api_key": "backup-secret",
            "model_map": {"assistant": "backup-model"},
        },
    )
    return response.json()


async def test_rate_limited_channel_fails_over_and_records_attempts(
    client, channel, backup, gateway_headers, admin_headers, upstream
):
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return (
            httpx.Response(429)
            if request.url.host == "primary.example"
            else httpx.Response(
                200, json={"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2}}
            )
        )

    upstream["handler"] = handler
    response = await client.post("/v1/chat/completions", json=BODY, headers=gateway_headers)
    assert response.status_code == 200
    assert calls == ["primary.example", "backup.example"]
    logs = (await client.get("/admin/requests", headers=admin_headers)).json()
    assert logs["total"] == 1
    row = logs["items"][0]
    assert row["id"] == response.headers["x-request-id"]
    assert [a["status"] for a in row["attempts"]] == [429, 200]
    assert row["usage"] == {"prompt_tokens": 4, "completion_tokens": 2}
    assert row["ttft_ms"] is None
    # The failed channel is cooling, so the next request goes straight to the backup.
    await client.post("/v1/chat/completions", json=BODY, headers=gateway_headers)
    assert calls[-1] == "backup.example" and len(calls) == 3


async def test_weighted_round_robin_distributes_requests(
    client, channel, backup, gateway_headers, admin_headers, upstream
):
    await client.patch("/admin/channels/1", json={"weight": 3}, headers=admin_headers)
    calls = Counter()

    def handler(request):
        calls[request.url.host] += 1
        return httpx.Response(200, json={"choices": []})

    upstream["handler"] = handler
    for _ in range(8):
        assert (
            await client.post("/v1/chat/completions", json=BODY, headers=gateway_headers)
        ).status_code == 200
    assert calls == {"primary.example": 6, "backup.example": 2}


async def test_budget_reservation_is_atomic_under_concurrent_requests(
    client, channel, gateway_headers, admin_headers, upstream
):
    await client.patch("/admin/channels/1", json={"request_budget": 1}, headers=admin_headers)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": []})

    upstream["handler"] = handler
    responses = await asyncio.gather(
        *[client.post("/v1/chat/completions", json=BODY, headers=gateway_headers) for _ in range(8)]
    )
    assert Counter(r.status_code for r in responses) == {200: 1, 503: 7}
    assert len(calls) == 1
    assert (await client.get("/admin/channels", headers=admin_headers)).json()[0][
        "requests_sent"
    ] == 1
    await client.post("/admin/channels/1/reset-budget", headers=admin_headers)
    assert (
        await client.post("/v1/chat/completions", json=BODY, headers=gateway_headers)
    ).status_code == 200


async def test_timeout_is_logged_and_recovered_after_cooldown(
    client, channel, gateway_headers, admin_headers, upstream
):
    now = [1000.0]
    client._transport.app.state.router = ChannelRouter(2, 30, clock=lambda: now[0])

    def handler(request):
        raise httpx.ReadTimeout("private-provider-diagnostic", request=request)

    upstream["handler"] = handler
    for _ in range(2):
        response = await client.post("/v1/chat/completions", json=BODY, headers=gateway_headers)
        assert response.status_code == 504
        assert "private-provider-diagnostic" not in response.text
    assert (
        await client.post("/v1/chat/completions", json=BODY, headers=gateway_headers)
    ).status_code == 503
    now[0] += 31
    upstream["handler"] = lambda _: httpx.Response(200, json={"choices": []})
    assert (
        await client.post("/v1/chat/completions", json=BODY, headers=gateway_headers)
    ).status_code == 200


async def test_stream_does_not_retry_after_output_and_has_no_false_success(
    client, channel, backup, gateway_headers, admin_headers, upstream
):
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    upstream["handler"] = handler
    await client.post(
        "/v1/chat/completions", json={**BODY, "stream": True}, headers=gateway_headers
    )
    assert calls == ["primary.example"]
    row = (await client.get("/admin/requests", headers=admin_headers)).json()["items"][0]
    assert row["status"] == "failed"
    assert row["http_status"] == 200  # Headers were already delivered before the stream failed.
    assert row["ttft_ms"] is not None


async def test_duplicate_usage_events_are_snapshots_and_metadata_is_not_ttft(
    client, channel, gateway_headers, admin_headers, upstream
):
    event = 'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":3}}\n\n'
    upstream["handler"] = lambda _: httpx.Response(
        200, text=event + event + "data: [DONE]\n\n", headers={"content-type": "text/event-stream"}
    )
    await client.post(
        "/v1/chat/completions", json={**BODY, "stream": True}, headers=gateway_headers
    )
    first = (await client.get("/admin/requests", headers=admin_headers)).json()["items"][0]
    second = (await client.get("/admin/requests", headers=admin_headers)).json()["items"][0]
    assert first["usage"] == {"prompt_tokens": 5, "completion_tokens": 3}
    assert first["ttft_ms"] is None
    assert first["duration_ms"] == second["duration_ms"]


async def test_closing_stream_releases_upstream_and_records_disconnect(
    client, channel, admin_headers
):
    app = client._transport.app
    trace = RequestTrace(SimpleNamespace(app=app), 1, "assistant")
    trace.channel_id = channel["id"]
    response = httpx.Response(200, text='data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n')
    generator = stream_events(response, "assistant", trace, app.state.router)
    assert "Hi" in await anext(generator)
    await generator.aclose()
    assert response.is_closed
    row = (await client.get("/admin/requests", headers=admin_headers)).json()["items"][0]
    assert row["status"] == "disconnected"
