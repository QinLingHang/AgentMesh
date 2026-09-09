import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";
import { AgentMeshClient, AgentMeshError } from "../dist/index.js";

const requests = [];
const server = http.createServer((req, res) => {
  const chunks = [];
  req.on("data", (chunk) => chunks.push(chunk));
  req.on("end", () => {
    const url = new URL(req.url, "http://fixture");
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : undefined;
    requests.push({ method: req.method, url, headers: req.headers, body });
    const send = (status, payload) => {
      const raw = Buffer.from(JSON.stringify(payload));
      res.writeHead(status, { "content-type": "application/json", "content-length": raw.length });
      res.end(raw);
    };
    if (req.headers.authorization !== "Bearer am_sk_fixture_secret") return send(401, { code: 40140, message: "bad key", data: null });
    if (url.pathname === "/openapi/v1/tasks/999") return send(404, { code: 40400, message: "not found", data: null });
    if (url.pathname === "/openapi/v1/marketplace") return send(200, { code: 0, message: "ok", data: [{ slug: "research-agent" }] });
    return send(200, { code: 0, message: "ok", data: { task: { id: 77 }, answer: "fixture" } });
  });
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
const client = new AgentMeshClient({ baseUrl: `http://127.0.0.1:${address.port}`, apiKey: "am_sk_fixture_secret" });

test("runTask sends bearer key and idempotency key", async () => {
  const result = await client.runTask({ task: "hello" }, { idempotencyKey: "run-once" });
  assert.equal(result.task.id, 77);
  const req = requests.at(-1);
  assert.equal(req.headers.authorization, "Bearer am_sk_fixture_secret");
  assert.equal(req.headers["idempotency-key"], "run-once");
  assert.equal(req.body.scheduler, "adaptive");
});

test("marketplace preserves query", async () => {
  const result = await client.marketplace({ query: "视觉 agent", kind: "AGENT", limit: 7 });
  assert.equal(result[0].slug, "research-agent");
  const req = requests.at(-1);
  assert.equal(req.url.searchParams.get("q"), "视觉 agent");
  assert.equal(req.url.searchParams.get("kind"), "AGENT");
  assert.equal(req.url.searchParams.get("limit"), "7");
});

test("error envelope throws AgentMeshError without leaking key", async () => {
  await assert.rejects(() => client.getTask(999), (error) => {
    assert.ok(error instanceof AgentMeshError);
    assert.equal(error.status, 404);
    assert.equal(error.code, 40400);
    assert.equal(String(error).includes("am_sk_fixture_secret"), false);
    return true;
  });
});

test.after(async () => { await new Promise((resolve) => server.close(resolve)); });
