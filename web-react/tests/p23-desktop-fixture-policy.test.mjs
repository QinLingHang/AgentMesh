import assert from "node:assert/strict";
import test from "node:test";
import {
  currentTurnToolMessage,
  isAuthoritativeToolLoopRequest,
  selectDesktopFixtureTool,
} from "../e2e/desktop-tool-fixture-policy.mjs";

const tool = (name) => ({ type: "function", function: { name } });
const runtimeSystem = { role: "system", content: "You are an AgentMesh Runtime execution model. The tools exposed in this turn were selected by AgentMesh." };

test("Desktop fixture follows Discovery-selected delete capability on the authoritative ToolLoop request", () => {
  const messages = [
    runtimeSystem,
    { role: "user", content: "Agent=desktop; capability=tool. Only handle your assigned subtask. Task: perform the requested file operation" },
  ];
  assert.equal(isAuthoritativeToolLoopRequest(messages), true);
  assert.equal(
    selectDesktopFixtureTool(messages, [tool("local.fs.list"), tool("local.fs.delete")]),
    "local.fs.delete",
  );
});

test("Desktop fixture refuses to create side effects for non-ToolLoop model requests", () => {
  const messages = [
    { role: "system", content: "planner or synthesis request" },
    { role: "user", content: "delete something" },
  ];
  assert.equal(isAuthoritativeToolLoopRequest(messages), false);
  assert.equal(selectDesktopFixtureTool(messages, [tool("local.fs.delete")]), null);
});

test("Desktop fixture uses list when authoritative Discovery exposed only list", () => {
  assert.equal(
    selectDesktopFixtureTool([runtimeSystem, { role: "user", content: "wrapped agent task" }], [tool("local.fs.list")]),
    "local.fs.list",
  );
});

test("Desktop fixture ignores a Tool result from an earlier user turn", () => {
  const messages = [
    runtimeSystem,
    { role: "user", content: "first turn" },
    { role: "assistant", content: null, tool_calls: [{ id: "a", function: { name: "local.fs.list" } }] },
    { role: "tool", tool_call_id: "a", content: "{}" },
    { role: "user", content: "second wrapped task" },
  ];
  assert.equal(selectDesktopFixtureTool(messages, [tool("local.fs.delete")]), "local.fs.delete");
});

test("Desktop fixture does not issue a second Tool call after the current turn already has an observation", () => {
  const messages = [
    runtimeSystem,
    { role: "user", content: "wrapped task" },
    { role: "assistant", content: null, tool_calls: [{ id: "b", function: { name: "local.fs.delete" } }] },
    { role: "tool", tool_call_id: "b", content: "{}" },
  ];
  assert.equal(selectDesktopFixtureTool(messages, [tool("local.fs.delete")]), null);
});

test("Desktop fixture never treats a historical Tool result as the current turn observation", () => {
  const messages = [
    runtimeSystem,
    { role: "user", content: "first turn" },
    { role: "assistant", content: null, tool_calls: [{ id: "old", function: { name: "local.fs.list" } }] },
    { role: "tool", tool_call_id: "old", content: "{\"ok\":true}" },
    { role: "user", content: "new turn without a Tool result yet" },
  ];
  assert.equal(currentTurnToolMessage(messages), null);
});
