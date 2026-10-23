"""Authenticated Jet Hub adapter. Provider credentials stay inside DSH."""
import http.cookiejar
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid

METHODS = frozenset("""
account.list account.create account.update account.delete account.reorder
account.refresh account.test account.retest account.reset
login.poll login.sendSms login.submitSms credits.balances credits.status
credits.claimAll credits.permanentLock model.list model.setDisabled
provider.status provider.getOrder provider.setEnabled
aggregate.catalog aggregate.expiryOrder aggregate.setRejected aggregate.setAllowed
aggregate.setOrder aggregate.setOrderMode usage.autoCheckin
""".split())

class RemoteError(Exception):
    pass

def loopback_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "http" or p.hostname not in ("127.0.0.1", "localhost", "::1") or p.username or p.password:
        raise ValueError("DSH 连接必须使用本机 http 回环地址")
    return p

def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()
                if k.lower().replace("_", "") not in
                {"apikey", "accesstoken", "refreshtoken", "token", "secret", "credentials", "credential"}}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value

class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        before, after = loopback_url(req.full_url), loopback_url(newurl)
        if before.netloc != after.netloc:
            raise RemoteError("拒绝跨地址跳转")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

class DshClient:
    def __init__(self, base_url, launch_url=None):
        self.base = base_url.rstrip("/")
        p = loopback_url(self.base)
        if p.path not in ("", "/"):
            raise ValueError("DSH 地址不能包含额外路径")
        if launch_url and loopback_url(launch_url).netloc != p.netloc:
            raise ValueError("DSH 授权链接与服务地址不一致")
        self.launch_url = launch_url
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), SameOriginRedirect())
        self.lock = threading.RLock()
        self.authenticated = False

    def call(self, method, payload=None, internal=False):
        if method not in METHODS and not (internal and method == "gateway.getEnabled"):
            raise ValueError("不支持的 Jet Hub 操作")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload 必须是对象")
        rid = str(uuid.uuid4())
        body = json.dumps({"type": "client-request", "rpcId": rid, "method": "jet-hub",
                           "payload": {"method": method, "payload": payload or {}}}).encode()
        with self.lock:
            try:
                if not self.authenticated and self.launch_url:
                    with self.opener.open(self.launch_url, timeout=10):
                        pass
                    self.authenticated = True
                req = urllib.request.Request(self.base + "/api/jet-hub", data=body,
                                             headers={"Content-Type": "application/json"})
                with self.opener.open(req, timeout=45) as response:
                    raw = response.read(4 * 1024 * 1024 + 1)
                    if len(raw) > 4 * 1024 * 1024:
                        raise RemoteError("DSH 响应过大")
                    data = json.loads(raw)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self.authenticated = False
                    raise RemoteError("DSH 授权已失效，请更新本机连接配置") from None
                raise RemoteError(f"DSH 返回 HTTP {e.code}") from None
            except (OSError, ValueError):
                raise RemoteError("DSH 服务不可达或返回了无效响应") from None
        if data.get("type") != "server-response" or data.get("rpcId") != rid:
            raise RemoteError("DSH 响应标识不匹配")
        result = data.get("result", {})
        if result.get("ok") is not True:
            # Keep provider diagnostics, never print launch links or credentials.
            raise RemoteError(str(result.get("error", {}).get("message", "Jet Hub 操作失败"))[:600])
        value = result.get("value")
        return value if internal else scrub(value)

