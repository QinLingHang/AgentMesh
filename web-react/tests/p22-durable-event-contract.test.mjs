import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const read = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');

test('SSE authenticates and re-checks task owner per poll', () => {
  const routes = read('backend-go/internal/router/durable_runtime.go');
  const handler = read('backend-go/internal/handler/durable_runtime.go');
  const repo = read('backend-go/internal/repository/durable_events.go');
  assert.match(routes, /protected\.GET\("\/tasks\/:id\/events"/);
  assert.match(handler, /h\.s\.TaskEvents\(c\.Request\.Context\(\), uid\(c\), taskID, after\)/);
  assert.match(repo, /t\.user_id = \?/);
  assert.match(repo, /j\.fence_epoch=\?/);
});

test('event replay has a durable cursor and no worker content', () => {
  const schema = read('backend-go/internal/db/durable_runtime_schema.go');
  const repo = read('backend-go/internal/repository/durable_events.go');
  const handler = read('backend-go/internal/handler/durable_runtime.go');
  assert.match(schema, /CREATE TABLE IF NOT EXISTS durable_task_events/);
  assert.match(schema, /KEY idx_durable_event_replay\(task_id, sequence\)/);
  assert.match(repo, /sequence>\?/);
  assert.match(handler, /Last-Event-ID/);
  assert.doesNotMatch(read('backend-go/internal/model/durable_events.go'), /resultText|leaseToken|toolArguments/);
});

test('React reconnects with last cursor and retains polling fallback', () => {
  const api = read('web-react/src/api.ts');
  const workspace = read('web-react/src/features/workspace/Workspace.tsx');
  assert.match(api, /"Last-Event-ID": String\(after\)/);
  assert.match(workspace, /cursor = Math\.max\(cursor, event\.sequence\)/);
  assert.match(workspace, /if \(!streaming\) refresh\(\)/);
  assert.match(workspace, /controller\.abort\(\)/);
  assert.match(workspace, /const persistedDurableTask = latestConversationTask/);
});
