#!/usr/bin/env python3
"""Verify routing using an isolated Go test database and local mock providers."""
import argparse
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18094")
    parser.add_argument("--login", default="data/personal/verify-login.json")
    parser.add_argument("--db", default="data/personal/verify.db")
    args = parser.parse_args()
    if Path(args.db).name != "verify.db":
        raise SystemExit("Only the disposable verify.db database is supported")
    auth = json.loads(Path(args.login).read_text())
    def api(path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(args.base + path, data=data,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + auth["token"]})
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                raw = response.read()
                return response.status, json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw.decode()
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)
    def gql(query, variables):
        status, result = api("/admin/graphql", {"query": query, "variables": variables})
        if status != 200 or result.get("errors"):
            raise RuntimeError("Test GraphQL operation failed")
        return result["data"]
    seen, servers, ids = [], [], []
    _, state = api("/admin/personal/status")
    original = state["budgets"]
    model = "personal-routing-verification-" + str(time.time_ns())
    def mock(label):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append(label)
                common = {"id": "chatcmpl-fixture", "created": int(time.time()), "model": request["model"]}
                if request.get("stream"):
                    frames = [
                        dict(common, object="chat.completion.chunk", choices=[{"index": 0, "delta": {"role": "assistant", "content": label}, "finish_reason": None}]),
                        dict(common, object="chat.completion.chunk", choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}],
                             usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}),
                    ]
                    body = ("".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n").encode()
                    mime = "text/event-stream"
                else:
                    body = json.dumps(dict(common, object="chat.completion",
                        choices=[{"index": 0, "message": {"role": "assistant", "content": label}, "finish_reason": "stop"}],
                        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})).encode()
                    mime = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_port
    try:
        for label in ["A", "B"]:
            port = mock(label)
            base = f"http://127.0.0.1:{port}/v1"
            created = gql("mutation($input:CreateChannelInput!){createChannel(input:$input){id}}", {"input": {
                "name": "Personal verify " + label + " " + str(time.time_ns()), "type": "openai", "baseURL": base,
                "credentials": {"apiKey": "local-test-fixture"}, "supportedModels": [model], "defaultTestModel": model,
            }})
            gid = created["createChannel"]["id"]
            gql("mutation($id:ID!){updateChannelStatus(id:$id,status:enabled){id}}", {"id": gid})
            with sqlite3.connect(args.db) as db:
                cid = db.execute("select id from channels where base_url=?", (base,)).fetchone()[0]
            ids.append((cid, gid))
        now = datetime.now(timezone.utc)
        def row(cid, hours, stale=False):
            bucket = {"remaining": 10, "unit": "credit"}
            if hours is not None:
                bucket["expires_at"] = (now + timedelta(hours=hours)).isoformat()
            return {"channel_id": cid, "models": [model], "source": "manual",
                    "observed_at": (now - timedelta(minutes=6) if stale else now).isoformat(),
                    "protect_permanent": True, "buckets": [bucket]}
        def scenario(accounts, expected):
            status, _ = api("/admin/personal/budgets", {"accounts": original + accounts})
            assert status == 200
            time.sleep(1.1)  # Go deliberately caches policy reads for one second.
            count = len(seen)
            status, response = api("/admin/playground/chat", {
                "model": model, "messages": [{"role": "user", "content": "local routing verification"}],
            })
            if expected is None:
                assert status == 503 and len(seen) == count, (status, seen[count:])
            else:
                assert status == 200 and seen[count:] == [expected], (status, response, seen[count:])
            return status
        first = scenario([row(ids[0][0], 1), row(ids[1][0], 2)], "A")
        protected = scenario([row(ids[0][0], None), row(ids[1][0], 2)], "B")
        stale = scenario([row(ids[0][0], 1, True), row(ids[1][0], 2, True)], None)
        print(json.dumps({"expiry_priority": first, "permanent_protection": protected, "stale_metadata_blocked": stale}))
    finally:
        api("/admin/personal/budgets", {"accounts": original})
        for _, gid in ids:
            gql("mutation($id:ID!){updateChannelStatus(id:$id,status:disabled){id}}", {"id": gid})
        for server in servers:
            server.shutdown()
            server.server_close()

if __name__ == "__main__":
    main()
