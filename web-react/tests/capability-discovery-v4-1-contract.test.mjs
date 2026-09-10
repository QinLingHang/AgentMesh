import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const tabs = fs.readFileSync(
  new URL("../src/features/run-details/RunDetailsTabs.tsx", import.meta.url),
  "utf8",
);
const details = fs.readFileSync(
  new URL("../src/features/run-details/RunDetails.tsx", import.meta.url),
  "utf8",
);
const panel = fs.readFileSync(
  new URL("../src/features/run-details/CapabilityDiscoveryPanel.tsx", import.meta.url),
  "utf8",
);

test("Run Details exposes autonomous capability discovery as a first-class tab", () => {
  assert.match(tabs, /\|\s*"capability"/);
  assert.match(tabs, /id:\s*"capability"/);
  assert.match(tabs, /label:\s*"能力发现"/);
  assert.match(tabs, /event\.kind\s*===\s*"capability_discovery"/);
  assert.match(details, /CapabilityDiscoveryPanel/);
  assert.match(details, /active\s*===\s*"capability"/);
});

test("capability discovery panel covers Tool MCP Skill and Knowledge selections", () => {
  assert.match(panel, /Tool、MCP、Skill 与当前会话可用知识库/);
  assert.match(panel, /selectedTools/);
  assert.match(panel, /selectedMCPServers/);
  assert.match(panel, /selectedMCPTools/);
  assert.match(panel, /selectedSkills/);
  assert.match(panel, /projectKnowledge/);
  assert.match(panel, /knowledgeSelected/);
  assert.match(panel, /知识库/);
  assert.match(panel, /candidates/);
  assert.match(panel, /最终选择/);
  assert.match(panel, /未选候选/);
});

test("capability discovery observability is metadata-only", () => {
  assert.match(panel, /不展示工具参数、返回正文或凭据/);
  assert.doesNotMatch(panel, /imageBase64/);
  assert.doesNotMatch(panel, /DESKTOP_BRIDGE_TOKEN/);
  assert.doesNotMatch(panel, /arguments/);
  assert.doesNotMatch(panel, /stdout/);
  assert.doesNotMatch(panel, /stderr/);
});

test("capability discovery shows conversation-aware continuation metadata", () => {
  assert.match(panel, /contextualized/);
  assert.match(panel, /historyTurns/);
  assert.match(panel, /承接最近上下文/);
  assert.match(panel, /简短承接语/);
});
