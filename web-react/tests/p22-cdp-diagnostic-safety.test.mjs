import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { cdpElementExists, reportFailurePreservingPrimary } from '../e2e/qa-cdp-diagnostics.mjs';

const harness = readFileSync(new URL('../e2e/v4-1-browser-e2e.mjs', import.meta.url), 'utf8');

test('element presence uses a primitive Boolean instead of serializing a DOM element by CDP value', async () => {
  const requests = [];
  const cdp = {
    async evaluate(expression) {
      requests.push(expression);
      assert.equal(expression, 'Boolean(document.querySelector("[data-testid=\\"run-details-open\\"]"))');
      return true;
    },
  };
  assert.equal(await cdpElementExists(cdp, '[data-testid="run-details-open"]'), true);
  assert.equal(requests.length, 1);
  assert.equal(await cdpElementExists({ evaluate: async () => false }, '#absent'), false);
  await assert.rejects(() => cdpElementExists({ evaluate: async () => ({ nodeType: 1 }) }, '#unsafe'), /non-boolean/);
});

test('CDP object-reference-chain diagnostic failure cannot replace the original Global assertion', async () => {
  const original = new Error('Timed out waiting for the Global knowledge marker');
  const logs = [];
  await assert.rejects(
    () => reportFailurePreservingPrimary(original, '[P22 GLOBAL]', async () => {
      return await cdpElementExists({
        evaluate: async () => { throw new Error('Object reference chain is too long'); },
      }, '[data-testid="run-details-open"]');
    }, (line) => logs.push(line)),
    (received) => received === original,
  );
  assert.deepEqual(logs, ['[P22 GLOBAL] safe failure diagnostic unavailable; original failure preserved']);
});

test('a broken diagnostic logger cannot replace the original project Citation failure', async () => {
  const original = new Error('Project citation not shown');
  await assert.rejects(
    () => reportFailurePreservingPrimary(original, '[P22 PROJECT]', async () => ({ citationGuardPassed: false }), () => {
      throw new Error('QA logging failed');
    }),
    (received) => received === original,
  );
});

test('only an explicit redacted summary is emitted; no model context, marker, or credentials', async () => {
  const original = new Error('Global answer missing');
  const logs = [];
  const modelContext = 'PRIVATE_SECRET_SHOULD_NOT_TRACE_123 auth-token-123 AGENTMESH_V41_GLOBAL_123';
  await assert.rejects(
    () => reportFailurePreservingPrimary(original, '[P22 GLOBAL]', async () => ({
      modelContextHadKnowledge: modelContext.includes('AGENTMESH_V41_GLOBAL_123'),
      runDetailsOpenerPresent: false,
    }), (line) => logs.push(line)),
    (received) => received === original,
  );
  assert.equal(logs.length, 1);
  assert.match(logs[0], /modelContextHadKnowledge":true/);
  assert.doesNotMatch(logs[0], /PRIVATE_SECRET|auth-token|AGENTMESH_V41_GLOBAL_/);
});

test('both acceptance failure paths preserve the original failure and never return raw DOM nodes by value', () => {
  assert.match(harness, /import \{ cdpElementExists, reportFailurePreservingPrimary \} from "\.\/qa-cdp-diagnostics\.mjs"/);
  assert.match(harness, /reportFailurePreservingPrimary\(error, "\[P22 GLOBAL\]"/);
  assert.match(harness, /reportFailurePreservingPrimary\(error, "\[P22 PROJECT\]"/);
  assert.match(harness, /runDetailsOpenerPresent: await cdpElementExists\(cdp,/);
  assert.doesNotMatch(harness, /Boolean\(await cdp\.evaluate\(`document\.querySelector\(/);
  assert.match(harness, /PROJECT citation guard must pass/);
  assert.match(harness, /User B retrieved User A GLOBAL Knowledge marker/);
});
