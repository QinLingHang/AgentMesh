import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {
  inspectProjectCitationDom,
  projectCitationReadyExpression,
  projectCitationDiagnosticExpression,
} from '../e2e/project-citation-dom.mjs';

const marker = 'AGENTMESH_V41_PROJECT_TEST_123';
const filename = 'project-123.txt';

function element(text = '', selectors = {}, attrs = {}, shown = true) {
  return {
    textContent: text,
    querySelector: selector => selectors[selector] ?? null,
    querySelectorAll: selector => selectors[selector] ?? [],
    getClientRects: () => shown ? [{}] : [],
    closest: () => shown ? null : { hidden: true },
    getAttribute: key => attrs[key] ?? null,
  };
}

function row({ markerInAnswer = true, source = true, button = true, filenameValue = filename,
  label = '[1]', buttonLabel = label, visible = true, durable = true } = {}) {
  const labelEl = element(label);
  const filenameEl = element(filenameValue);
  const summary = source ? element('SOURCES', {
    '.citation-summary-index': labelEl, strong: filenameEl,
  }) : null;
  const btn = button ? element(buttonLabel, {}, { 'aria-label': `查看引用 ${buttonLabel}：${filenameValue}` }) : null;
  const answer = element(markerInAnswer ? `项目测试标记是 ${marker} ${label}。` : '无当前项目标记。', {
    'button.citation-marker': btn ? [btn] : [],
  });
  const selectors = { '.citation-answer-content': answer };
  if (source) {
    selectors['.citation-sources'] = element('SOURCES');
    selectors['.citation-sources .citation-source-summary'] = summary;
  }
  return element('row', selectors, durable ? { 'data-message-id': '42' } : {}, visible);
}

function page(rows, streaming = []) {
  return {
    querySelectorAll: selector => selector === '[data-testid="message-assistant"]'
      ? rows : selector === '[data-testid="assistant-streaming-answer"]' ? streaming : [],
  };
}

test('durable answer must contain a clickable marker linked to the same row source', () => {
  const result = inspectProjectCitationDom(page([row()]), marker, filename);
  assert.equal(result.ready, true);
  assert.equal(result.rows[0].sourceLabelMatchesMarker, true);
});

test('plain [1] plus SOURCES is not an interactive citation', () => {
  const result = inspectProjectCitationDom(page([row({button:false})]), marker, filename);
  assert.equal(result.ready, false);
  assert.equal(result.rows[0].hasSource, true);
  assert.equal(result.rows[0].markerButtonCount, 0);
});

test('the first matching row may be stale; a later durable matching row can pass', () => {
  assert.equal(inspectProjectCitationDom(page([row({button:false}), row()]), marker, filename).ready, true);
});

test('streaming marker, missing durable id, hidden row, and source in a different row cannot pass', () => {
  assert.equal(inspectProjectCitationDom(page([], [row()]), marker, filename).ready, false);
  assert.equal(inspectProjectCitationDom(page([row({durable:false})]), marker, filename).ready, false);
  assert.equal(inspectProjectCitationDom(page([row({visible:false})]), marker, filename).ready, false);
  assert.equal(inspectProjectCitationDom(page([row({source:false}), row({markerInAnswer:false})]), marker, filename).ready, false);
});

test('source filename, label and current answer must all agree; a nonmatching identity fails', () => {
  assert.equal(inspectProjectCitationDom(page([row({filenameValue:'other.txt'})]), marker, filename).ready, false);
  assert.equal(inspectProjectCitationDom(page([row({buttonLabel:'[2]'})]), marker, filename).ready, false);
  assert.equal(inspectProjectCitationDom(page([row({markerInAnswer:false})]), marker, filename).ready, false);
});

test('actual CDP expressions return only Boolean or bounded redacted JSON, never DOM objects', () => {
  const doc = page([row()]);
  const ready = vm.runInNewContext(projectCitationReadyExpression(marker, filename), { document: doc });
  const diagnostic = vm.runInNewContext(projectCitationDiagnosticExpression(marker, filename), { document: doc });
  assert.equal(ready, true);
  assert.equal(diagnostic.ready, true);
  assert.equal(diagnostic.matchedAnswerRows, 1);
  assert.doesNotMatch(JSON.stringify(diagnostic), /AGENTMESH_V41_PROJECT|project-123|项目测试标记|data-message-id/);
  assert.equal(inspectProjectCitationDom(page(Array.from({length:11},()=>row())), marker, filename).rows.length, 8);
});

test('production Markdown generates safe internal fragments while retaining default URL sanitization', () => {
  for (const file of ['../src/features/citation/CitationAnswer.tsx', '../src/features/extensions/CitationAnswer.tsx']) {
    const source = fs.readFileSync(new URL(file, import.meta.url), 'utf8');
    assert.match(source, /url: `#agentmesh-citation-\$\{citation\.citationId\}`/);
    assert.match(source, /\^#agentmesh-citation-\\d\+\$/);
    assert.doesNotMatch(source, /urlTransform\s*=/);
    assert.doesNotMatch(source, /url: `citation:/);
  }
});

test('real E2E still checks project guard, unused Global boundary and cross-user isolation', () => {
  const script = fs.readFileSync(new URL('../e2e/v4-1-browser-e2e.mjs', import.meta.url), 'utf8');
  assert.match(script, /projectCitationReadyExpression\(projectMarker, `project-\$\{stamp\}\.txt`\)/);
  assert.match(script, /projectCitationDiagnosticExpression/);
  assert.match(script, /PROJECT citation guard must pass/);
  assert.match(script, /PROJECT citation guard must allow/);
  assert.match(script, /unbound GLOBAL Knowledge leaked into PROJECT conversation/);
  assert.match(script, /User B retrieved User A GLOBAL Knowledge marker/);
  assert.doesNotMatch(script, /Body:\\n\$\{body\}/);
});
