// Legacy contract marker: Eval / Policy
import type { RunResult } from "../../types";
import { formatDurationMs } from "../../utils/format";

function clampPercent(
  value: number,
) {
  return Math.max(
    0,
    Math.min(
      100,
      value,
    ),
  );
}

function HealthRow({
  label,
  value,
  detail,
  percent,
}: {
  label: string;
  value: string;
  detail: string;
  percent: number;
}) {
  const safePercent =
    clampPercent(percent);

  return (
    <div className="run-health-row">
      <div className="run-health-row-head">
        <div>
          <strong>
            {label}
          </strong>

          <small>
            {detail}
          </small>
        </div>

        <span>
          {value}
        </span>
      </div>

      <div className="run-health-track">
        <span
          style={{
            width: `${safePercent}%`,
          }}
        />
      </div>
    </div>
  );
}

export function RunHealthPanel({
  result,
}: {
  result: RunResult;
}) {
  const o = result.observability;

  const traceErrors =
    result.trace.filter(
      (event) =>
        event.status === "error",
    );

  const mcpErrors =
    traceErrors.filter(
      (event) =>
        event.kind === "mcp",
    );

  const agentRate =
    o.agentAttempts > 0
      ? o.agentSuccesses /
        o.agentAttempts
      : 1;

  const totalDagNodes =
    o.dagCompletedNodes +
    o.dagSkippedNodes;

  const dagRate =
    totalDagNodes > 0
      ? o.dagCompletedNodes /
        totalDagNodes
      : 1;

  const qualityRate =
    o.qualityEvaluations > 0
      ? o.averageQuality
      : 0;

  const modelLatencyShare =
    result.elapsedMs > 0
      ? o.modelLatencyMs /
        result.elapsedMs
      : 0;

  const scorecardWarning =
    result.scorecard != null &&
    result.scorecard.status !== "pass";

  const hasWarning =
    o.agentFailures > 0 ||
    traceErrors.length > 0 ||
    scorecardWarning;

  return (
    <section className="detail-section run-health-section">
      <div className="section-title">
        <div>
          <h3>
            执行健康度
          </h3>

          <p>
            从 Agent 成功率、DAG 完成度、Quality 和模型耗时占比快速判断本次运行状态。
          </p>
        </div>

        <span
          className={`run-health-badge ${
            hasWarning
              ? "warning"
              : "healthy"
          }`}
        >
          {hasWarning
            ? "需要关注"
            : "运行健康"}
        </span>
      </div>

      <div className="run-health-card">
        <HealthRow
          label="Agent 成功率"
          value={
            o.agentAttempts > 0
              ? `${(
                  agentRate * 100
                ).toFixed(0)}%`
              : "-"
          }
          detail={`${o.agentSuccesses}/${o.agentAttempts} attempts`}
          percent={
            agentRate * 100
          }
        />

        <HealthRow
          label="DAG 完成度"
          value={
            totalDagNodes > 0
              ? `${(
                  dagRate * 100
                ).toFixed(0)}%`
              : "-"
          }
          detail={`${o.dagCompletedNodes} completed · ${o.dagSkippedNodes} skipped`}
          percent={
            dagRate * 100
          }
        />

        <HealthRow
          label="Quality"
          value={
            o.qualityEvaluations > 0
              ? o.averageQuality.toFixed(
                  3,
                )
              : "-"
          }
          detail={`${o.qualityEvaluations} evaluations`}
          percent={
            qualityRate * 100
          }
        />

        <HealthRow
          label="模型耗时占比"
          value={
            result.elapsedMs > 0
              ? `${(
                  modelLatencyShare * 100
                ).toFixed(0)}%`
              : "-"
          }
          detail={`${formatDurationMs(
            o.modelLatencyMs,
          )} / ${formatDurationMs(
            result.elapsedMs,
          )}`}
          percent={
            modelLatencyShare * 100
          }
        />
      </div>

      {hasWarning && (
        <div className="run-health-warning-list">
          {scorecardWarning && result.scorecard && (
            <div>
              <strong>
                Eval / Policy
              </strong>

              <span>
                Score {result.scorecard.overallScore.toFixed(3)} · {result.scorecard.violations.length} violation(s).
              </span>
            </div>
          )}

          {o.agentFailures > 0 && (
            <div>
              <strong>
                Agent Failure
              </strong>

              <span>
                {o.agentFailures} 次 Agent 尝试失败。
              </span>
            </div>
          )}

          {mcpErrors.length > 0 && (
            <div>
              <strong>
                MCP Error
              </strong>

              <span>
                {mcpErrors.length} 个 MCP 事件失败，详情请查看 Trace。
              </span>
            </div>
          )}

          {traceErrors.length >
            mcpErrors.length && (
            <div>
              <strong>
                Runtime Trace
              </strong>

              <span>
                还有 {traceErrors.length - mcpErrors.length} 个非 MCP 错误事件。
              </span>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
