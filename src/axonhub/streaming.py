import anyio
from fastapi.responses import StreamingResponse


class GatewayStreamingResponse(StreamingResponse):
    """Watch disconnects even while the upstream is silent between chunks."""

    def __init__(self, content, *, trace, upstream, **kwargs):
        super().__init__(content, **kwargs)
        self.trace = trace
        self.upstream = upstream

    async def __call__(self, scope, receive, send):
        try:
            async with anyio.create_task_group() as group:

                async def watch_disconnect():
                    await self.listen_for_disconnect(receive)
                    if self.trace.status != "success":
                        self.trace.status = "disconnected"
                    group.cancel_scope.cancel()

                group.start_soon(watch_disconnect)
                try:
                    await self.stream_response(send)
                except OSError:
                    self.trace.status = "disconnected"
                finally:
                    group.cancel_scope.cancel()
        finally:
            with anyio.CancelScope(shield=True):
                await self.body_iterator.aclose()
                await self.upstream.aclose()
                await self.trace.finish()
