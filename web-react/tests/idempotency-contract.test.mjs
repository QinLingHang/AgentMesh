import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');

test('Knowledge Runtime client identity survives auth refresh retry', () => {
  const api = read('web-react/src/api.ts');
  assert.match(api, /const clientRequestId = input\.clientRequestId \?\? crypto\.randomUUID\(\)/);
  assert.match(api, /clientRequestId,\s*task: input\.task/);
  assert.match(api, /runTaskStream\(\{ \.\.\.input, clientRequestId \}, callbacks, false\)/);
});

test('Knowledge Runtime durable idempotency uses atomic MySQL key + payload fingerprint', () => {
  const schema = read('backend-go/internal/db/durable_runtime_schema.go');
  const repo = read('backend-go/internal/repository/durable_runtime.go');
  const durable = read('backend-go/internal/service/durable_runtime.go');
  assert.match(schema, /PRIMARY KEY \(user_id, client_request_id\)/);
  assert.match(repo, /INSERT INTO task_submission_keys/);
  assert.match(repo, /ErrSubmissionConflict/);
  assert.match(repo, /INSERT INTO messages\(conversation_id, role, content, status, request_id, metadata_json\)/);
  assert.match(durable, /LookupDurableSubmission/);
  assert.match(durable, /sha256\.Sum256\(fingerprintJSON\)/);
});
