import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const harness = fs.readFileSync(new URL('../e2e/v4-1-browser-e2e.mjs', import.meta.url), 'utf8');
const rail = fs.readFileSync(new URL('../src/features/workspace/SessionRail.tsx', import.meta.url), 'utf8');

function section(start, end) {
  const from = harness.indexOf(start);
  const to = harness.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `missing browser helper boundary: ${start}`);
  return harness.slice(from, to);
}

test('P22 V4.1 waits for the real project-create control after model service reload', () => {
  const helper = section('async function openCreateProjectWhenReady(cdp)', 'async function verifyAndReloadV41ModelService');
  const wait = helper.indexOf('await waitFor(');
  const click = helper.indexOf('await clickSelector(');
  assert.ok(wait >= 0 && click > wait, 'must wait before clicking the create-project button');
  assert.match(helper, /\.app-shell\.tab-workspace/);
  assert.match(helper, /\.session-rail/);
  assert.match(helper, /project-create-open/);
  assert.match(helper, /button\.isConnected/);
  assert.match(helper, /!button\.disabled/);
  assert.match(helper, /button\.getClientRects\(\)\.length > 0/);
  assert.match(helper, /getComputedStyle\(rail\)\.pointerEvents !== 'none'/);
  assert.match(helper, /20000/);
  assert.doesNotMatch(helper, /sleep\(|project-create-empty|apiRequest\(/,
    'must not bypass the real UI gate with a sleep, alternate element or API call');
  assert.match(rail, /data-testid="project-create-open"/,
    'the test must target a real production button');
});

test('P22 V4.1 retains the project dialog and light-theme assertions after readiness', () => {
  const flow = section('    // P20 light-theme regression:', '    // P20 Conversation Memory Reliability:');
  assert.match(flow, /await openCreateProjectWhenReady\(cdp\)/);
  assert.doesNotMatch(flow, /await clickSelector\(cdp, '\[data-testid="project-create-open"\]'/,
    'one-shot clicking in the test body reintroduces the hydration race');
  assert.match(flow, /project-name-input/);
  assert.match(flow, /projectControlTheme\.inputBg/);
  assert.match(flow, /projectControlTheme\.textareaBg/);
  assert.match(flow, /await clickText\(cdp, "取消"\)/);
});
