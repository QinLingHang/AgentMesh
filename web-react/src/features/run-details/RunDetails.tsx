import { useState } from "react";
import type { RunResult } from "../../types";
import { RunOverview } from "./RunOverview";
import { ExecutionTimeline } from "./ExecutionTimeline";
import { FeedbackTable } from "./FeedbackTable";
import { RunDetailsHeader } from "./RunDetailsHeader";
import {
  RunDetailsTabs,
  type RunDetailTab,
} from "./RunDetailsTabs";
import { RunSummaryStrip } from "./RunSummaryStrip";
import { RAGTracePanel } from "./RAGTracePanel";
import { AgentDAGPanel } from "./AgentDAGPanel";
import { MemoryTracePanel } from "./MemoryTracePanel";
import { ToolMCPTracePanel } from "./ToolMCPTracePanel";
import { EvalScorecardPanel } from "./EvalScorecardPanel";
import { RoutingTracePanel } from "./RoutingTracePanel";
import { ReliabilityTracePanel } from "./ReliabilityTracePanel";

export function RunDetails({
  result,
  onBack,
  display = "page",
}: {
  result: RunResult;
  onBack: () => void;
  display?: "page" | "drawer";
}) {
  const [active, setActive] =
    useState<RunDetailTab>(
      "overview",
    );

  return (
    <div
      className={`run-details-page ${
        display === "drawer"
          ? "run-details-drawer-mode"
          : ""
      }`}
    >
      <RunDetailsHeader
        result={result}
        onBack={onBack}
        display={display}
      />

      <RunSummaryStrip
        result={result}
      />

      <RunDetailsTabs
        result={result}
        active={active}
        onChange={setActive}
      />

      <main className="run-detail-content">
        {active === "overview" && (
          <RunOverview
            result={result}
          />
        )}

        {active === "rag" && (
          <RAGTracePanel
            result={result}
          />
        )}

        {active === "agent-dag" && (
          <AgentDAGPanel
            result={result}
          />
        )}

        {active === "memory" && (
          <MemoryTracePanel
            trace={result.trace}
          />
        )}

        {active === "tool-mcp" && (
          <ToolMCPTracePanel
            trace={result.trace}
          />
        )}

        {active === "eval" && (
          <EvalScorecardPanel
            result={result}
          />
        )}

        {active === "routing" && (
          <RoutingTracePanel
            trace={result.trace}
          />
        )}

        {active === "reliability" && (
          <ReliabilityTracePanel
            trace={result.trace}
          />
        )}

        {active === "trace" && (
          <section className="trace-panel-shell">
            <div className="section-title">
              <div>
                <h3>
                  完整 Trace
                </h3>

                <p>
                  保留 Runtime 原始执行事件，便于调试与可观测性分析。
                </p>
              </div>

              <span className="detail-count-badge">
                {result.trace.length} events
              </span>
            </div>

            <ExecutionTimeline
              trace={result.trace}
            />
          </section>
        )}

        {active === "feedback" && (
          <section className="feedback-panel-shell">
            <div className="section-title">
              <div>
                <h3>
                  Agent Feedback
                </h3>

                <p>
                  本次运行产生的 Agent 质量、耗时、成本与成功状态反馈。
                </p>
              </div>
            </div>

            <FeedbackTable
              feedback={result.agentFeedback}
            />
          </section>
        )}
      </main>
    </div>
  );
}
