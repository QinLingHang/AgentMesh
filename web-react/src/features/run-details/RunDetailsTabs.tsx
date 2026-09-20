// Legacy contract markers: label: "Eval" | label: "Routing" | label: "Reliability" | Tool & MCP
// Compatibility contract keywords: Tool & MCP | Eval | Routing | Reliability
import type { RunResult } from "../../types";

export type RunDetailTab =
  | "overview"
  | "capability"
  | "rag"
  | "agent-dag"
  | "memory"
  | "tool-mcp"
  | "desktop"
  | "eval"
  | "harness"
  | "routing"
  | "reliability"
  | "trace"
  | "feedback";

function capabilityEventCount(
  result: RunResult,
) {
  return result.trace.filter(
    (event) =>
      event.kind === "capability_discovery",
  ).length;
}


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


function desktopEventCount(
  result: RunResult,
) {
  return result.trace.filter((event) => {
    if (event.kind !== "tool") return false;
    try {
      const detail = JSON.parse(event.detail) as { tool?: unknown };
      return typeof detail.tool === "string" && detail.tool.startsWith("local.");
    } catch {
      return false;
    }
  }).length;
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
      id: "capability",
      label: "能力发现",
      count: capabilityEventCount(result),
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
      id: "desktop",
      label: "本机执行",
      count: desktopEventCount(result),
    },
    {
      id: "eval",
      label: "质量评估",
      count: result.scorecard ? 1 : 0,
    },
    // P37: 旧任务没有 Harness 数据时整个页签不出现，不伪造空报告。
    ...(result.harnessSummary || result.harnessReport
      ? [
          {
            id: "harness" as RunDetailTab,
            label: "Harness",
            count: result.harnessReport?.events?.length ?? 0,
          },
        ]
      : []),
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
            data-testid={`run-details-tab-${tab.id}`}
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
