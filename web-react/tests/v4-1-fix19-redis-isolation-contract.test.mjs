import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const e2ePath = path.resolve(import.meta.dirname, "..", "e2e", "v4-1-browser-e2e.mjs");
const source = fs.readFileSync(e2ePath, "utf8");

test("V4.1 FIX19 isolates Runtime short-term memory from persistent development Redis", () => {
  assert.match(source, /V4_1_E2E_RUNTIME_REDIS_URL\s*\|\|\s*"redis:\/\/127\.0\.0\.1:6382\/14"/);
  assert.match(source, /runtimeRedisDb\s*===\s*0/);
  assert.match(source, /DB 0 is reserved for normal development\/runtime state/);
  assert.match(source, /agentmesh:v4-1:e2e:\$\{stamp\}:memory/);
  assert.match(source, /REDIS_URL:\s*runtimeRedisUrl/);
  assert.match(source, /MEMORY_BACKEND:\s*"redis"/);
  assert.match(source, /MEMORY_KEY_PREFIX:\s*runtimeMemoryPrefix/);
});

test("V4.1 FIX19 cleans only its per-run memory namespace and never flushes shared Redis", () => {
  assert.match(source, /async function cleanupRuntimeMemory/);
  assert.match(source, /scan_iter\(match=\(prefix \+ ":\*"\)/);
  assert.match(source, /client\.delete\(\*keys\)/);
  assert.ok(!/\.flushall\s*\(/i.test(source), "V4.1 harness must never call FLUSHALL Redis");
  assert.ok(!/\.flushdb\s*\(/i.test(source), "V4.1 harness must never call FLUSHDB Redis");
});

test("V4.1 FIX19 performs namespace hygiene both before Runtime start and after Runtime shutdown", () => {
  const calls = source.match(/cleanupRuntimeMemory\(runtimePython, runtimeRoot, runtimeRedisUrl, runtimeMemoryPrefix\)/g) ?? [];
  assert.ok(calls.length >= 2, `expected cleanupRuntimeMemory before and after Runtime, got ${calls.length}`);
  assert.match(source, /await cleanupRuntimeMemory\(runtimePython, runtimeRoot, runtimeRedisUrl, runtimeMemoryPrefix\);[\s\S]*?runtime = spawn/);
  assert.match(source, /stopChild\(child\)[\s\S]*?cleanupRuntimeMemory\(runtimePython, runtimeRoot, runtimeRedisUrl, runtimeMemoryPrefix\)/);
});
