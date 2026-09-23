// Deterministic model-fixture policy for Desktop Tool turns.
//
// AgentMesh Runtime/Discovery already decided which capabilities are relevant
// before this fixture receives the OpenAI-compatible request. The fixture must
// not perform a second natural-language router. It must also avoid treating an
// unrelated model request that merely happens to carry tools as the executable
// ToolLoop decision.

const TOOL_LOOP_SYSTEM_MARKER = "You are an AgentMesh Runtime execution model.";

function currentTurnMessages(messages) {
  const list = Array.isArray(messages) ? messages : [];
  let latestUserIndex = -1;
  for (let index = list.length - 1; index >= 0; index -= 1) {
    if (list[index]?.role === "user") {
      latestUserIndex = index;
      break;
    }
  }
  return latestUserIndex >= 0 ? list.slice(latestUserIndex + 1) : list;
}

export function isAuthoritativeToolLoopRequest(messages) {
  return (Array.isArray(messages) ? messages : []).some((message) =>
    message?.role === "system"
    && typeof message?.content === "string"
    && message.content.includes(TOOL_LOOP_SYSTEM_MARKER));
}

export function currentTurnToolMessage(messages) {
  const turnMessages = currentTurnMessages(messages);
  return [...turnMessages].reverse().find((message) => message?.role === "tool") ?? null;
}

export function selectDesktopFixtureTool(messages, tools) {
  // Only the Runtime ToolLoop owns executable Tool decisions. Other model
  // requests (planning, synthesis, memory, eval) must never manufacture a side
  // effect merely because their payload happens to contain a tools field.
  if (!isAuthoritativeToolLoopRequest(messages)) return null;
  if (currentTurnToolMessage(messages)) return null;

  const names = new Set(
    (Array.isArray(tools) ? tools : [])
      .map((item) => item?.function?.name ?? "")
      .filter(Boolean),
  );

  // Discovery is authoritative for capability choice. High-risk means
  // Governance must suspend before execution, not that the model should hide
  // the attempted call.
  if (names.has("local.fs.delete")) return "local.fs.delete";
  if (names.has("local.fs.list")) return "local.fs.list";
  return null;
}
