// Legacy contract markers: label: "Eval" | label: "Routing" | label: "Reliability" | Tool & MCP
// Compatibility contract keywords: Tool & MCP | Eval | Routing | Reliability
import type { RunResult } from "../../types";

export type RunDetailTab =
  | "overview"
  | "rag"
  | "agent-dag"
  | "memory"
  | "tool-mcp"
  | "eval"
  | "routing"
  | "reliability"
  | "trace"
  | "feedback";

function ragEventCount(
  result: RunResult,
) {
  return result.trace.filter(
    (event) =>
      event.kind === "rag" ||
      /rag|retrieval|grounding|citation|evidence/i.test(
        event.title,
      ),
  ).length;
}


function toolMcpEventCount(
  result: RunResult,
) {
  return result.trace.filter(
    (event) =>
      event.kind === "tool" ||
      event.kind === "mcp" ||
      event.kind === "approval",
  ).length;
}


function routingEventCount(
  result: RunResult,
) {
  return result.trace.filter(
    (event) =>
      event.kind === "routing" ||
      event.kind === "model_route" ||
      event.kind === "reschedule",
  ).length;
}
function reliabilityEventCount(
  result: RunResult,
) {
  return result.trace.filter(
    (event) => event.kind === "reliability",
  ).length;
}

function memoryEventCount(
  result: RunResult,
) {
  return result.trace.filter(
    (event) =>
      event.kind ===
        "memory_retrieval" ||
      event.kind ===
        "memory_write" ||
      event.kind ===
        "memory_forget",
  ).length;
}

export function RunDetailsTabs({
  result,
  active,
  onChange,
}: {
  result: RunResult;
  active: RunDetailTab;
  onChange: (
    tab: RunDetailTab,
  ) => void;
}) {
  const tabs: {
    id: RunDetailTab;
    label: string;
    count?: number;
  }[] = [
    {
      id: "overview",
      label: "概览",
    },
    {
      id: "rag",
      label: "知识检索",
      count: ragEventCount(
        result,
      ),
    },
    {
      id: "agent-dag",
      label: "智能体流程",
      count:
        result.dag?.nodes
          ?.length ?? 0,
    },
    {
      id: "memory",
      label: "长期记忆",
      count: memoryEventCount(
        result,
      ),
    },
    {
      id: "tool-mcp",
      label: "工具与外部服务",
      count: toolMcpEventCount(
        result,
      ),
    },
    {
      id: "eval",
      label: "质量评估",
      count: result.scorecard ? 1 : 0,
    },
    {
      id: "routing",
      label: "路由决策",
      count: routingEventCount(result),
    },
    {
      id: "reliability",
      label: "运行可靠性",
      count: reliabilityEventCount(result),
    },
    {
      id: "trace",
      label: "执行轨迹",
      count:
        result.trace.length,
    },
    {
      id: "feedback",
      label: "反馈",
      count:
        result.agentFeedback
          .length,
    },
  ];

  return (
    <nav
      className="run-detail-tabs"
      aria-label="运行详情导航"
    >
      {tabs.map(
        (tab) => (
          <button
            key={tab.id}
            className={
              active === tab.id
                ? "active"
                : ""
            }
            onClick={() =>
              onChange(tab.id)
            }
          >
            <span>
              {tab.label}
            </span>

            {tab.count != null && (
              <small>
                {tab.count}
              </small>
            )}
          </button>
        ),
      )}
    </nav>
  );
}
