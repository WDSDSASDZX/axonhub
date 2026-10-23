import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from axonhub_personal.bridge import DshClient, RemoteError, scrub
from axonhub_personal.optimizer import optimize, atomic_json, validate
from axonhub_personal.__main__ import Worker, handler
import urllib.request
import urllib.error

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)

def account(cid=1, hours=2, protected=False):
    return {"channel_id": cid, "source": "manual", "observed_at": NOW.isoformat(),
            "protect_permanent": protected, "models": ["model"],
            "buckets": [{"remaining": 10, "unit": "credit", "expires_at": (NOW + timedelta(hours=hours)).isoformat()}]}

class OptimizerTests(unittest.TestCase):
    def test_expiring_credit_ranks_first(self):
        p = optimize([account(1, 48), account(2, 2)], NOW)
        self.assertEqual([r["channel_id"] for r in p["rules"]], [2, 1])
        self.assertTrue(all(r["eligible"] for r in p["rules"]))

    def test_protected_mixed_wallet_requires_upstream_guarantee(self):
        a = account(protected=True)
        a["buckets"].append({"remaining": 9, "unit": "credit"})
        self.assertFalse(optimize([a], NOW)["rules"][0]["eligible"])
        a["upstream_expiry_first"] = True
        self.assertTrue(optimize([a], NOW)["rules"][0]["eligible"])

    def test_expired_unknown_and_stale_are_not_spendable(self):
        for a in [account(hours=-1), dict(account(), observed_at=(NOW-timedelta(minutes=6)).isoformat()),
                  dict(account(), buckets=[])]:
            self.assertFalse(optimize([a], NOW)["rules"][0]["eligible"])

    def test_invalid_balance_and_duplicate_channel_rejected(self):
        a = account()
        a["buckets"][0]["remaining"] = float("nan")
        with self.assertRaises(ValueError):
            validate([a])
        with self.assertRaises(ValueError):
            validate([account(), account()])

    def test_atomic_policy_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"policy.json"
            atomic_json(p, optimize([account()], NOW))
            self.assertEqual(json.loads(p.read_text())["version"], 1)
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)

class BridgeTests(unittest.TestCase):
    def test_secret_fields_are_removed(self):
        self.assertEqual(scrub({"accounts": [{"name": "one", "refreshToken": "secret", "apiKey": {"value": "secret"}}]}),
                         {"accounts": [{"name": "one"}]})

    def test_remote_destinations_and_arbitrary_methods_rejected(self):
        with self.assertRaises(ValueError):
            DshClient("https://example.com")
        with self.assertRaises(ValueError):
            DshClient("http://127.0.0.1:3080").call("backup.export")

    def test_wire_protocol_and_correlation(self):
        class Mock(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                result = {"type": "server-response", "rpcId": data["rpcId"],
                          "result": {"ok": True, "value": {"accounts": [{"id": "a", "accessToken": "secret"}]}}}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Mock)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            result = DshClient(f"http://127.0.0.1:{server.server_port}").call("account.list", {"provider": "codearts"})
            self.assertEqual(result, {"accounts": [{"id": "a"}]})
        finally:
            server.shutdown(); server.server_close()

    def test_worker_requires_token_and_persists_budget(self):
        with tempfile.TemporaryDirectory() as d:
            worker = Worker({}, d)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler(worker))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base + "/status")
                self.assertEqual(error.exception.code, 401)
                req = urllib.request.Request(base + "/budgets", data=json.dumps({"accounts": [account()]}).encode(),
                    headers={"Authorization": "Bearer " + worker.token, "Content-Type": "application/json"})
                with urllib.request.urlopen(req) as response:
                    self.assertEqual(json.load(response)["rules"][0]["channel_id"], 1)
                self.assertEqual(worker.accounts()[0]["channel_id"], 1)
            finally:
                server.shutdown(); server.server_close()

if __name__ == "__main__":
    unittest.main()

