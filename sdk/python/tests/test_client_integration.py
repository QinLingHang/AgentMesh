from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from agentmesh import AgentMeshClient, AgentMeshError


class FixtureHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, *_args):
        return

    def _json(self, status: int, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.requests.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "body": body})
        if self.headers.get("Authorization") != "Bearer am_sk_fixture_secret":
            self._json(401, {"code": 40140, "message": "bad key", "data": None})
            return
        self._json(200, {"code": 0, "message": "ok", "data": {"task": {"id": 77}, "answer": "fixture"}})

    def do_GET(self):
        parsed = urlparse(self.path)
        self.requests.append({"method": "GET", "path": parsed.path, "query": parse_qs(parsed.query), "headers": dict(self.headers)})
        if parsed.path == "/openapi/v1/tasks/999":
            self._json(404, {"code": 40400, "message": "not found", "data": None})
            return
        if parsed.path == "/openapi/v1/marketplace":
            self._json(200, {"code": 0, "message": "ok", "data": [{"slug": "research-agent"}]})
            return
        self._json(200, {"code": 0, "message": "ok", "data": {"id": 77}})


class ClientIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FixtureHandler.requests = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.client = AgentMeshClient(f"http://127.0.0.1:{cls.server.server_port}", "am_sk_fixture_secret", timeout=2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_run_task_sends_auth_idempotency_and_defaults(self):
        data = self.client.run_task("hello", idempotency_key="run-once")
        self.assertEqual(data["task"]["id"], 77)
        req = FixtureHandler.requests[-1]
        self.assertEqual(req["headers"].get("Authorization"), "Bearer am_sk_fixture_secret")
        self.assertEqual(req["headers"].get("Idempotency-Key"), "run-once")
        self.assertEqual(req["body"]["scheduler"], "adaptive")
        self.assertEqual(req["body"]["executionMode"], "auto")

    def test_marketplace_query_is_encoded(self):
        data = self.client.marketplace(query="视觉 agent", kind="AGENT", limit=7)
        self.assertEqual(data[0]["slug"], "research-agent")
        req = FixtureHandler.requests[-1]
        self.assertEqual(req["query"]["q"], ["视觉 agent"])
        self.assertEqual(req["query"]["kind"], ["AGENT"])
        self.assertEqual(req["query"]["limit"], ["7"])

    def test_error_envelope_becomes_agentmesh_error(self):
        with self.assertRaises(AgentMeshError) as ctx:
            self.client.get_task(999)
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(ctx.exception.code, 40400)
        self.assertNotIn("am_sk_fixture_secret", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
