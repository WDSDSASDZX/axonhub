"""A local fake provider for demonstrating failover without spending API credits."""

import argparse
import asyncio
import json

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()


@app.post("/fail/v1/chat/completions")
async def limited():
    return JSONResponse({"error": {"message": "Demo rate limit"}}, status_code=429)


@app.post("/v1/chat/completions")
async def completion(request: Request):
    body = await request.json()
    usage = {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
    if not body.get("stream"):
        return {
            "id": "demo-completion",
            "object": "chat.completion",
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "你好，这是本地模拟响应。"},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        }

    async def events():
        for text in ["你好，", "这是本地", "模拟的流式响应。"]:
            await asyncio.sleep(0.04)
            payload = {
                "id": "demo-stream",
                "object": "chat.completion.chunk",
                "model": body["model"],
                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'choices': [], 'usage': usage})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18092)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
