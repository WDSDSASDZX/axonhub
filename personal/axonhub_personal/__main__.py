"""Run with: PYTHONPATH=personal python3 -m axonhub_personal --config <private JSON>."""
import argparse
import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .bridge import DshClient, RemoteError
from .optimizer import atomic_json, optimize, validate

class Worker:
    def __init__(self, config, data_dir):
        self.data = Path(data_dir).resolve()
        self.data.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.token_file = self.data / "worker.token"
        if not self.token_file.exists():
            fd = os.open(self.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_urlsafe(32))
        self.token = self.token_file.read_text().strip()
        if len(self.token) < 24:
            raise ValueError("worker token 长度不足")
        self.dsh = DshClient(config.get("dsh_url", "http://127.0.0.1:3080"), config.get("launch_url"))
        self.lock = threading.RLock()

    def accounts(self):
        p = self.data / "budgets.json"
        return json.loads(p.read_text()) if p.exists() else []

    def publish(self):
        with self.lock:
            policy = optimize(self.accounts())
            atomic_json(self.data / "policy.json", policy)
            return policy

    def dispatch(self, method, path, payload):
        if method == "GET" and path == "/status":
            return {"service": "axonhub-personal", "dsh_url": self.dsh.base, "policy": self.publish(),
                    "budgets": self.accounts()}
        if method == "POST" and path == "/rpc":
            return self.dsh.call(payload.get("method"), payload.get("payload", {}))
        if method == "POST" and path == "/budgets":
            rows = validate(payload.get("accounts"))
            with self.lock:
                atomic_json(self.data / "budgets.json", rows)
                return self.publish()
        if method == "GET" and path == "/connection":
            value = self.dsh.call("gateway.getEnabled", {}, internal=True)
            if not value.get("running") or not value.get("apiKey"):
                raise RemoteError("Jet Hub 模型网关尚未启用")
            address = value.get("address")
            if isinstance(address, dict):
                host, port = address.get("host"), address.get("port")
                address = (f"http://{host}:{port}/v1" if host in ("127.0.0.1", "localhost") and type(port) is int
                           else address.get("baseUrl") or address.get("url") or address.get("apiBase"))
            if not isinstance(address, str):
                raise RemoteError("无法识别 Jet Hub 网关地址")
            loop = urlsplit(address)
            if loop.hostname not in ("127.0.0.1", "localhost", "::1"):
                raise RemoteError("仅允许连接本机 Jet Hub 网关")
            return {"name": "Jet Hub", "base_url": address.rstrip("/"),
                    "api_key": value["apiKey"]["value"],
                    "models": [m["id"] for m in value.get("models", []) if isinstance(m.get("id"), str)]}
        raise ValueError("未知接口")

def handler(worker):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + worker.token):
                self.reply(401, {"error": "未授权"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 0 or size > 1024 * 1024:
                    self.reply(413, {"error": "请求过大"})
                    return
                payload = json.loads(self.rfile.read(size)) if size else {}
                if not isinstance(payload, dict):
                    raise ValueError("请求必须是对象")
                value = worker.dispatch(self.command, urlsplit(self.path).path, payload)
                self.reply(200, value)
            except RemoteError as e:
                self.reply(502, {"error": str(e)})
            except (ValueError, KeyError, TypeError):
                self.reply(400, {"error": "请求数据无效，请检查字段和时间格式"})
            except Exception:
                self.reply(500, {"error": "后台操作失败，请检查本机配置"})

        def reply(self, status, value):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return Handler

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", default="data/personal")
    parser.add_argument("--port", type=int, default=8093)
    args = parser.parse_args()
    config_path = Path(args.config)
    if os.name != "nt" and config_path.stat().st_mode & 0o077:
        raise SystemExit("连接配置包含授权信息，权限必须为 600")
    worker = Worker(json.loads(config_path.read_text()), args.data_dir)
    worker.publish()
    stopped = threading.Event()
    def refresh():
        while not stopped.wait(30):
            try:
                worker.publish()
            except Exception:
                pass  # Keep the previous policy; its expiry makes Go fail closed.
    thread = threading.Thread(target=refresh, daemon=True)
    thread.start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(worker))
    print(f"AxonHub Personal worker: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        stopped.set()
        server.server_close()

if __name__ == "__main__":
    main()

