import fs from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const source = fs.readFileSync(new URL("../src/features/workspace/Workspace.tsx", import.meta.url), "utf8");

function section(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `missing source boundary: ${start}`);
  return source.slice(from, to);
}

test("a prepend cancels every pending auto-follow generation and retains reader ownership", () => {
  const prepend = section("const handleLoadOlderHistory", "useLayoutEffect(() => {");
  assert.match(prepend, /cancelScheduledMessageScroll\(\)/);
  assert.match(prepend, /shouldAutoFollowMessagesRef\.current = false/);
  assert.match(prepend, /messageHistoryReaderOwnedRef\.current = true/);
  assert.match(prepend, /messageReaderScrollIntentRef\.current = false/);
  const cancel = section("const cancelScheduledMessageScroll", "const captureVisibleMessageAnchor");
  assert.match(cancel, /messageScrollGenerationRef\.current \+= 1/);
});

test("every scheduled auto-follow frame checks owner and generation before writing scrollTop", () => {
  const follow = section("const scrollMessagesToBottom", "const handleMessageScroll");
  assert.match(follow, /const generation = \+\+messageScrollGenerationRef\.current/);
  assert.match(follow, /generation === messageScrollGenerationRef\.current/);
  assert.match(follow, /messageHistoryAnchorRef\.current == null/);
  assert.match(follow, /!messageHistoryReaderOwnedRef\.current/);
  assert.match(follow, /shouldAutoFollowMessagesRef\.current/);
  assert.equal((follow.match(/if \(!canContinueFollowing\(\)\)/g) || []).length, 2);
  assert.equal((follow.match(/forceMessageScrollBottom\(/g) || []).length, 3);
});

test("a synthetic scroll event after prepend cannot reactivate following; an actual return to bottom can", () => {
  const scroll = section("const handleMessageScroll =", "const cancelScheduledMessageScroll");
  assert.match(scroll, /messageHistoryAnchorRef\.current != null/);
  assert.match(scroll, /messageHistoryReaderOwnedRef\.current && !messageReaderScrollIntentRef\.current/);
  assert.match(scroll, /shouldAutoFollowMessagesRef\.current = distanceFromBottom <= 96/);
  assert.match(scroll, /messageHistoryReaderOwnedRef\.current = false/);
  const intent = section("const handleMessageScrollIntent", "const handleLoadOlderHistory");
  assert.match(intent, /messageReaderScrollIntentRef\.current = true/);
  const opening = section("useLayoutEffect\(\(\) => {", "useEffect\(\(\) => {\n    const contentNode");
  assert.match(opening, /conversationChanged[\s\S]*messageHistoryReaderOwnedRef\.current = false/);
});
