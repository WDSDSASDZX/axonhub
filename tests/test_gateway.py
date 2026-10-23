import json

import httpx
import pytest

BODY = {"model": "assistant", "messages": [{"role": "user", "content": "Hello"}]}


async def test_chat_requires_client_key(client):
    assert (await client.post("/v1/chat/completions", json=BODY)).status_code == 401


async def test_completion_maps_model_and_uses_provider_credentials(
    client, channel, gateway_headers, upstream
):
    def handler(request):
        assert request.url == "https://primary.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-provider-token"
        assert json.loads(request.content)["model"] == "provider-model"
        return httpx.Response(
            200, json={"model": "provider-model", "choices": [{"message": {"content": "Hi"}}]}
        )

    upstream["handler"] = handler
    response = await client.post("/v1/chat/completions", json=BODY, headers=gateway_headers)
    assert response.status_code == 200
    assert response.json()["model"] == "assistant"
    assert response.json()["choices"][0]["message"]["content"] == "Hi"


async def test_unknown_model_and_revoked_key_are_rejected(client, admin_headers, gateway_headers):
    response = await client.post("/v1/chat/completions", json=BODY, headers=gateway_headers)
    assert response.status_code == 404
    await client.delete("/admin/keys/1", headers=admin_headers)
    assert (
        await client.post("/v1/chat/completions", json=BODY, headers=gateway_headers)
    ).status_code == 401


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
async def test_stream_preserves_unicode_tool_calls_and_usage(
    client, channel, gateway_headers, upstream, ending
):
    events = [
        {"model": "provider-model", "choices": [{"delta": {"content": "你好"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-1"}]}}]},
        {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}},
    ]
    content = "".join(f"data: {json.dumps(event)}{ending}{ending}" for event in events)
    content += f"data: [DONE]{ending}{ending}"
    upstream["handler"] = lambda _: httpx.Response(
        200, text=content, headers={"content-type": "text/event-stream"}
    )
    response = await client.post(
        "/v1/chat/completions", json={**BODY, "stream": True}, headers=gateway_headers
    )
    assert response.status_code == 200
    assert "你好" in response.text
    assert "call-1" in response.text
    assert '"prompt_tokens": 3' in response.text
    assert '"model": "assistant"' in response.text
    assert response.text.endswith("data: [DONE]\n\n")


async def test_broken_stream_is_reported_without_a_false_done(
    client, channel, gateway_headers, upstream
):
    upstream["handler"] = lambda _: httpx.Response(
        200, text='data: {"choices": []}\n\n', headers={"content-type": "text/event-stream"}
    )
    response = await client.post(
        "/v1/chat/completions", json={**BODY, "stream": True}, headers=gateway_headers
    )
    assert "incomplete_upstream_stream" in response.text
    assert "[DONE]" not in response.text


async def test_upstream_failure_does_not_expose_response_body(
    client, channel, gateway_headers, upstream
):
    upstream["handler"] = lambda _: httpx.Response(401, text="private-upstream-debug-data")
    response = await client.post("/v1/chat/completions", json=BODY, headers=gateway_headers)
    assert response.status_code == 502
    assert "private-upstream-debug-data" not in response.text
