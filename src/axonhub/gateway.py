import asyncio
import json
import time
from typing import Annotated

import anyio
import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from axonhub.db import Channel, ClientKey
from axonhub.routing import reserve_attempt
from axonhub.security import cipher, require_client
from axonhub.streaming import GatewayStreamingResponse
from axonhub.telemetry import RequestTrace

router = APIRouter(prefix="/v1")
AuthenticatedKey = Annotated[ClientKey, Depends(require_client)]


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = Field(min_length=1, max_length=200)
    messages: list[dict] = Field(min_length=1)
    stream: bool = False
    stream_options: dict | None = None


def error_response(status: int, code: str, trace: RequestTrace) -> JSONResponse:
    trace.http_status = status
    return JSONResponse(
        status_code=status,
        content={
            "error": {"message": code.replace("_", " "), "type": "gateway_error", "code": code}
        },
        headers={"X-Request-ID": trace.id},
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


async def stream_events(response: httpx.Response, alias: str, trace: RequestTrace, routing):
    pending: list[str] = []
    completed = False
    trace.http_status = 200
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
                trace.status = "success"
                routing.success(trace.channel_id)
                yield "data: [DONE]\n\n"
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                yield 'data: {"error":{"code":"invalid_upstream_event"}}\n\n'
                return
            if not isinstance(payload, dict) or "error" in payload:
                yield 'data: {"error":{"code":"invalid_upstream_event"}}\n\n'
                return
            trace.observe(payload)
            if "model" in payload:
                payload["model"] = alias
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        if not completed:
            yield 'data: {"error":{"code":"incomplete_upstream_stream"}}\n\n'
    except httpx.HTTPError:
        yield 'data: {"error":{"code":"upstream_stream_error"}}\n\n'
    except (asyncio.CancelledError, GeneratorExit):
        trace.status = "disconnected"
        raise
    finally:
        if trace.status == "failed":
            routing.failure(trace.channel_id)
        with anyio.CancelScope(shield=True):
            await response.aclose()
            await trace.finish()


async def dispatch(body: ChatInput, request: Request, trace: RequestTrace):
    candidates = [c for c in await available_channels(request) if body.model in c.model_map]
    if not candidates:
        return None, error_response(404, "model_not_configured", trace)
    routing = request.app.state.router
    upstream = request.app.state.upstream
    ordered = await routing.order(candidates)
    last_status, last_code = 503, "no_available_channel"
    for channel in ordered:
        if len(trace.attempts) >= request.app.state.settings.max_attempts:
            break
        if not await reserve_attempt(request.app.state.database, channel.id):
            continue
        trace.channel_id = channel.id
        attempt = {"channel_id": channel.id, "channel": channel.name}
        trace.attempts.append(attempt)
        started = time.perf_counter()
        payload = body.model_dump(exclude_none=True)
        payload["model"] = channel.model_map[body.model]
        if body.stream:
            payload["stream_options"] = {**(body.stream_options or {}), "include_usage": True}
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
        except httpx.HTTPError as exc:
            last_status = 504 if isinstance(exc, httpx.TimeoutException) else 502
            last_code = "upstream_timeout" if last_status == 504 else "upstream_connection_error"
            attempt.update(status=last_status, outcome=last_code)
            routing.failure(channel.id)
            continue
        finally:
            attempt["headers_ms"] = round((time.perf_counter() - started) * 1000, 2)
        attempt["status"] = response.status_code
        if response.status_code == 200:
            if body.stream and "text/event-stream" not in response.headers.get("content-type", ""):
                await response.aclose()
                routing.failure(channel.id)
                attempt["outcome"] = "invalid_content_type"
                last_status, last_code = 502, "invalid_upstream_content_type"
                continue
            return response, None
        status = response.status_code
        await response.aclose()
        attempt["outcome"] = "upstream_rejected_request"
        last_status, last_code = 502, "upstream_rejected_request"
        if status in (401, 403, 429) or status >= 500:
            routing.failure(channel.id, immediate=status in (401, 403, 429))
            continue
        return None, error_response(status if status in (400, 413, 422) else 502, last_code, trace)
    return None, error_response(last_status, last_code, trace)


@router.post("/chat/completions")
async def chat(body: ChatInput, request: Request, key: AuthenticatedKey):
    trace = RequestTrace(request, key.id, body.model)
    response = None
    handed_to_stream = False
    try:
        response, failure = await dispatch(body, request, trace)
        if failure is not None:
            return failure
        if body.stream:
            handed_to_stream = True
            return GatewayStreamingResponse(
                stream_events(response, body.model, trace, request.app.state.router),
                trace=trace,
                upstream=response,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "X-Request-ID": trace.id,
                },
            )
        try:
            await response.aread()
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get("choices"), list):
                request.app.state.router.failure(trace.channel_id)
                return error_response(502, "invalid_upstream_response", trace)
            result["model"] = body.model
            trace.usage = result.get("usage") if isinstance(result.get("usage"), dict) else None
            trace.status, trace.http_status = "success", 200
            request.app.state.router.success(trace.channel_id)
            return JSONResponse(result, headers={"X-Request-ID": trace.id})
        except (ValueError, httpx.HTTPError):
            request.app.state.router.failure(trace.channel_id)
            return error_response(502, "invalid_upstream_response", trace)
    except asyncio.CancelledError:
        trace.status = "disconnected"
        raise
    finally:
        if not handed_to_stream:
            with anyio.CancelScope(shield=True):
                if response is not None:
                    await response.aclose()
                await trace.finish()
