import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');

test('worker phases and task states use the same durable replay journal', () => {
  const repo = read('backend-go/internal/repository/durable_events.go');
  const schema = read('backend-go/internal/db/durable_runtime_schema.go');
  assert.match(schema, /ADD COLUMN event_type/);
  assert.match(repo, /AppendDurableWorkerPhase/);
  assert.match(repo, /FOR UPDATE/);
  assert.match(repo, /j\.lease_token=\?/);
  assert.match(repo, /j\.fence_epoch=\?/);
  assert.match(repo, /event_type, phase, phase_status/);
});

test('UI handles sanitized worker phases without treating them as task transitions', () => {
  const api = read('web-react/src/api.ts');
  const workspace = read('web-react/src/features/workspace/Workspace.tsx');
  assert.match(api, /eventType\?: "state" \| "trace"/);
  assert.match(workspace, /event\.eventType === "trace"/);
  assert.match(workspace, /if \(event\.eventType !== "trace"\) refresh\(\)/);
});

test('worker never forwards trace title, detail, tool arguments or results', () => {
  const worker = read('runtime-python/app/distributed/execution_manager.py');
  assert.match(worker, /"ordinal": ordinal/);
  assert.match(worker, /"phase": kind/);
  assert.doesNotMatch(worker, /"detail": getattr\(trace/);
  assert.doesNotMatch(worker, /"title": getattr\(trace/);
});