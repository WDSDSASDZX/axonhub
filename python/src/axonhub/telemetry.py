import time
import uuid

import anyio
from fastapi import Request

from axonhub.db import RequestLog


class RequestTrace:
    def __init__(self, request: Request, key_id: int, model: str):
        self.database = request.app.state.database
        self.id = str(uuid.uuid4())
        self.started = time.perf_counter()
        self.key_id = key_id
        self.model = model
        self.channel_id: int | None = None
        self.ttft_ms: float | None = None
        self.usage: dict | None = None
        self.attempts: list[dict] = []
        self.status = "failed"
        self.http_status = 502
        self._finished = False

    def observe(self, payload: dict) -> None:
        if isinstance(payload.get("usage"), dict):
            self.usage = payload["usage"]  # Snapshot: replace duplicate usage events.
        choices = payload.get("choices")
        for choice in choices if isinstance(choices, list) else []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                continue
            visible = (
                delta.get("content") or delta.get("reasoning_content") or delta.get("tool_calls")
            )
            if visible and self.ttft_ms is None:
                self.ttft_ms = (time.perf_counter() - self.started) * 1000

    async def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        duration = (time.perf_counter() - self.started) * 1000
        if self.attempts:
            self.attempts[-1]["outcome"] = self.status
        with anyio.CancelScope(shield=True):
            async with self.database.sessions() as session:
                session.add(
                    RequestLog(
                        id=self.id,
                        client_key_id=self.key_id,
                        model=self.model,
                        channel_id=self.channel_id,
                        status=self.status,
                        http_status=self.http_status,
                        duration_ms=duration,
                        ttft_ms=self.ttft_ms,
                        usage=self.usage,
                        attempts=self.attempts,
                    )
                )
                await session.commit()
