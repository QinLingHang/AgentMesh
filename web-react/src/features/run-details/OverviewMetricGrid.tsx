import type { RunResult } from "../../types";
import {
  formatCompactNumber,
  formatDurationMs,
} from "../../utils/format";

function MetricCard({
  label,
  value,
  hint,
  accent,
}: {
  label: string;
  value: string;
  hint: string;
  accent?: "success" | "warning" | "neutral";
}) {
  return (
    <article
      className={`overview-metric-card ${
        accent
          ? `overview-metric-${accent}`
          : ""
      }`}
    >
      <span className="overview-metric-label">
        {label}
      </span>

      <strong className="overview-metric-value">
        {value}
      </strong>

      <small className="overview-metric-hint">
        {hint}
      </small>
    </article>
  );
}

export function OverviewMetricGrid({
  result,
}: {
  result: RunResult;
}) {
  const o = result.observability;

  const agentSuccessRate =
    o.agentAttempts > 0
      ? o.agentSuccesses /
        o.agentAttempts
      : 0;

  const agentAccent =
    o.agentFailures > 0
      ? "warning"
      : o.agentAttempts > 0
        ? "success"
        : "neutral";

  return (
    <section>
      <div className="section-title overview-section-title">
        <div>
          <h3>
            Runtime 指标
          </h3>

          <p>
            本次运行最关键的模型、工具、Agent 与 DAG 资源消耗。
          </p>
        </div>
      </div>

      <div className="overview-metric-grid">
        <MetricCard
          label="Model Calls"
          value={`${o.modelCalls}`}
          hint={`${formatCompactNumber(
            o.modelTotalTokens,
          )} Tokens`}
        />

        <MetricCard
          label="Model Latency"
          value={formatDurationMs(
            o.modelLatencyMs,
          )}
          hint={`${formatCompactNumber(
            o.modelInputTokens,
          )} in · ${formatCompactNumber(
            o.modelOutputTokens,
          )} out`}
        />

        <MetricCard
          label="工具与外部服务"
          value={`${o.toolCalls} / ${o.mcpEvents}`}
          hint="工具调用 / 外部服务事件"
        />

        <MetricCard
          label="Agent Success"
          value={
            o.agentAttempts > 0
              ? `${(
                  agentSuccessRate * 100
                ).toFixed(0)}%`
              : "-"
          }
          hint={`${o.agentSuccesses} success · ${o.agentFailures} failed`}
          accent={agentAccent}
        />

        <MetricCard
          label="Reschedules"
          value={`${o.reschedules}`}
          hint="Runtime 动态重调度"
          accent={
            o.reschedules > 0
              ? "warning"
              : "neutral"
          }
        />

        <MetricCard
          label="DAG Nodes"
          value={`${o.dagCompletedNodes}`}
          hint={`${o.dagSkippedNodes} skipped`}
          accent={
            o.dagCompletedNodes > 0
              ? "success"
              : "neutral"
          }
        />
      </div>
    </section>
  );
}
