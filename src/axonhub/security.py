import hashlib
import secrets
from typing import Annotated

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from axonhub.db import ClientKey

bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def digest_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def cipher(request: Request) -> Fernet:
    return Fernet(request.app.state.settings.encryption_key.get_secret_value().encode())


async def require_admin(request: Request, credentials: Credentials) -> None:
    expected = request.app.state.settings.admin_token.get_secret_value()
    if not expected:
        raise HTTPException(503, "Run axonhub init before using management endpoints")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(401, "Invalid administrator token")


async def require_client(request: Request, credentials: Credentials) -> ClientKey:
    if credentials is None:
        raise HTTPException(401, "A client API key is required")
    async with request.app.state.database.sessions() as session:
        key = await session.scalar(
            select(ClientKey).where(
                ClientKey.key_hash == digest_key(credentials.credentials),
                ClientKey.enabled.is_(True),
            )
        )
    if key is None:
        raise HTTPException(401, "Invalid client API key")
    return key
