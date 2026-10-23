import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import func, select, update

from axonhub.db import Channel, ClientKey, RequestLog
from axonhub.security import cipher, digest_key, require_admin

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


class ChannelInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(max_length=2048)
    api_key: SecretStr
    model_map: dict[str, str] = Field(min_length=1)
    weight: int = Field(default=1, ge=1, le=100)
    request_budget: int | None = Field(default=None, ge=0)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use an HTTP(S) base URL without credentials, query or fragment")
        return value.rstrip("/")

    @field_validator("model_map")
    @classmethod
    def validate_models(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not k.strip() or not v.strip() or len(k) > 200 for k, v in value.items()):
            raise ValueError("Model names must be nonempty and at most 200 characters")
        return value


class ChannelPatch(BaseModel):
    enabled: bool | None = None
    weight: int | None = Field(default=None, ge=1, le=100)
    request_budget: int | None = Field(default=None, ge=0)


class KeyInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def public_channel(channel: Channel) -> dict:
    return {
        "id": channel.id,
        "name": channel.name,
        "base_url": channel.base_url,
        "model_map": channel.model_map,
        "enabled": channel.enabled,
        "weight": channel.weight,
        "request_budget": channel.request_budget,
        "requests_sent": channel.requests_sent,
    }


@router.get("/channels")
async def channels(request: Request):
    async with request.app.state.database.sessions() as session:
        rows = await session.scalars(select(Channel).order_by(Channel.id))
        return [public_channel(row) for row in rows]


@router.post("/channels", status_code=201)
async def create_channel(body: ChannelInput, request: Request):
    channel = Channel(
        **body.model_dump(exclude={"api_key"}),
        encrypted_key=cipher(request).encrypt(body.api_key.get_secret_value().encode()).decode(),
    )
    async with request.app.state.database.sessions() as session:
        session.add(channel)
        await session.commit()
        return public_channel(channel)


@router.patch("/channels/{channel_id}")
async def update_channel(channel_id: int, body: ChannelPatch, request: Request):
    async with request.app.state.database.sessions() as session:
        channel = await session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(404, "Channel not found")
        for field, value in body.model_dump(exclude_unset=True).items():
            if value is None and field != "request_budget":
                raise HTTPException(422, f"{field} cannot be null")
            setattr(channel, field, value)
        await session.commit()
        return public_channel(channel)


@router.get("/keys")
async def keys(request: Request):
    async with request.app.state.database.sessions() as session:
        rows = await session.scalars(select(ClientKey).order_by(ClientKey.id))
        return [
            {"id": row.id, "name": row.name, "prefix": row.prefix, "enabled": row.enabled}
            for row in rows
        ]


@router.post("/keys", status_code=201)
async def create_key(body: KeyInput, request: Request):
    value = "ax-" + secrets.token_urlsafe(32)
    key = ClientKey(name=body.name, key_hash=digest_key(value), prefix=value[:12])
    async with request.app.state.database.sessions() as session:
        session.add(key)
        await session.commit()
        return {"id": key.id, "name": key.name, "key": value}


@router.delete("/keys/{key_id}", status_code=204)
async def revoke_key(key_id: int, request: Request):
    async with request.app.state.database.sessions() as session:
        key = await session.get(ClientKey, key_id)
        if key is None:
            raise HTTPException(404, "Client key not found")
        key.enabled = False
        await session.commit()


@router.post("/channels/{channel_id}/reset-budget", status_code=204)
async def reset_budget(channel_id: int, request: Request):
    async with request.app.state.database.sessions() as session:
        result = await session.execute(
            update(Channel).where(Channel.id == channel_id).values(requests_sent=0)
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Channel not found")


@router.get("/requests")
async def requests(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    model: str | None = None,
):
    query = select(RequestLog)
    if status:
        query = query.where(RequestLog.status == status)
    if model:
        query = query.where(RequestLog.model == model)
    async with request.app.state.database.sessions() as session:
        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await session.scalars(
            query.order_by(RequestLog.created_at.desc()).limit(limit).offset(offset)
        )
        return {
            "total": total,
            "items": [
                {
                    "id": row.id,
                    "created_at": row.created_at.isoformat(),
                    "model": row.model,
                    "channel_id": row.channel_id,
                    "status": row.status,
                    "http_status": row.http_status,
                    "duration_ms": round(row.duration_ms, 2),
                    "ttft_ms": row.ttft_ms,
                    "usage": row.usage,
                    "attempts": row.attempts,
                }
                for row in rows
            ],
        }
