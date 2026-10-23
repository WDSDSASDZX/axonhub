import json
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from axonhub.db import Channel, ClientKey
from axonhub.security import cipher, require_client

router = APIRouter(prefix="/v1")
AuthenticatedKey = Annotated[ClientKey, Depends(require_client)]


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(min_length=1, max_length=200)
    messages: list[dict] = Field(min_length=1)
    stream: bool = False


def error_response(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {"message": code.replace("_", " "), "type": "gateway_error", "code": code}
        },
    )


async def available_channels(request: Request) -> list[Channel]:
    async with request.app.state.database.sessions() as session:
        result = await session.scalars(
            select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)
        )
        return list(result)


@router.get("/models")
async def models(request: Request, key: AuthenticatedKey):
    aliases = sorted(
        {alias for channel in await available_channels(request) for alias in channel.model_map}
    )
    return {
        "object": "list",
        "data": [{"id": alias, "object": "model", "owned_by": "gateway"} for alias in aliases],
    }


async def stream_events(response: httpx.Response, alias: str):
    pending: list[str] = []
    completed = False
    try:
        async for line in response.aiter_lines():
            if line:
                pending.append(line)
                continue
            data = "\n".join(item[5:].lstrip() for item in pending if item.startswith("data:"))
            pending.clear()
            if not data:
                continue
            if data == "[DONE]":
                completed = True
                yield "data: [DONE]\n\n"
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                yield 'data: {"error":{"code":"invalid_upstream_event"}}\n\n'
                return
            if not isinstance(payload, dict):
                yield 'data: {"error":{"code":"invalid_upstream_event"}}\n\n'
                return
            if "model" in payload:
                payload["model"] = alias
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        if not completed:
            yield 'data: {"error":{"code":"incomplete_upstream_stream"}}\n\n'
    except httpx.HTTPError:
        yield 'data: {"error":{"code":"upstream_stream_error"}}\n\n'
    finally:
        await response.aclose()


@router.post("/chat/completions")
async def chat(body: ChatInput, request: Request, key: AuthenticatedKey):
    channels = [c for c in await available_channels(request) if body.model in c.model_map]
    if not channels:
        return error_response(404, "model_not_configured")
    channel = channels[0]
    payload = body.model_dump()
    payload["model"] = channel.model_map[body.model]
    if body.stream:
        payload["stream_options"] = {**(payload.get("stream_options") or {}), "include_usage": True}
    upstream = request.app.state.upstream
    try:
        response = await upstream.send(
            upstream.build_request(
                "POST",
                channel.base_url + "/chat/completions",
                headers={
                    "Authorization": "Bearer "
                    + cipher(request).decrypt(channel.encrypted_key.encode()).decode(),
                    "Accept": "text/event-stream" if body.stream else "application/json",
                },
                json=payload,
            ),
            stream=True,
        )
    except httpx.TimeoutException:
        return error_response(504, "upstream_timeout")
    except httpx.HTTPError:
        return error_response(502, "upstream_connection_error")
    if response.status_code != 200:
        await response.aclose()
        return error_response(502, "upstream_rejected_request")
    if body.stream:
        if "text/event-stream" not in response.headers.get("content-type", ""):
            await response.aclose()
            return error_response(502, "invalid_upstream_content_type")
        return StreamingResponse(
            stream_events(response, body.model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    try:
        await response.aread()
        result = response.json()
        if not isinstance(result, dict) or "choices" not in result:
            return error_response(502, "invalid_upstream_response")
        result["model"] = body.model
        return JSONResponse(result)
    except (ValueError, httpx.HTTPError):
        return error_response(502, "invalid_upstream_response")
    finally:
        await response.aclose()
