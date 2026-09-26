// Legacy contract markers: Routing Decisions | Selected | Score | Degraded
// Compatibility contract keywords: Routing Decisions | Selected | Score | Degraded
import type { TraceEvent } from "../../types";

type Detail = Record<string, unknown>;

function parseDetail(detail: string): Detail {
  if (!detail) return {};
  try {
    const value = JSON.parse(detail);
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as Detail)
      : {};
  } catch {
    return {};
  }
}

function numberText(value: unknown, digits = 3) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "—";
}

function candidateRows(detail: Detail) {
  const value = detail.candidates;
  return Array.isArray(value)
    ? value.filter(
        (item): item is Detail =>
          !!item && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

export function RoutingTracePanel({
  trace,
}: {
  trace: TraceEvent[];
}) {
  const events = trace.filter(
    (event) =>
      event.kind === "routing" ||
      event.kind === "model_route" ||
      event.kind === "reschedule",
  );

  return (
    <section className="routing-panel-shell">
      <div className="section-title">
        <div>
          <h3>路由决策</h3>
          <p>
            查看智能体、模型与备用方案的多目标选择依据。这里只展示评分与策略元数据，不展示用户原文或私密上下文。
          </p>
        </div>
        <span className="detail-count-badge">{events.length} 条记录</span>
      </div>

      {events.length === 0 ? (
        <div className="routing-empty-state">
          当前运行没有自适应路由记录。固定调度、贪心调度或单一模型运行方式会保持原有执行路径。
        </div>
      ) : (
        <div className="routing-event-list">
          {events.map((event, index) => {
            const detail = parseDetail(event.detail);
            const candidates = candidateRows(detail);
            const selected =
              detail.selectedAgentName ??
              detail.selectedRuntimeId ??
              detail.to ??
              detail.model ??
              detail.strategy ??
              "—";
            const reason =
              typeof detail.reason === "string"
                ? detail.reason
                : Array.isArray(detail.reasonCodes)
                  ? detail.reasonCodes.filter((item): item is string => typeof item === "string").join(", ")
                  : "";

            return (
              <article className="routing-event-card" key={`${event.elapsedMs}-${index}`}>
                <header>
                  <div>
                    <strong>{event.title}</strong>
                    <small>{event.kind} · {event.elapsedMs} ms</small>
                  </div>
                  <span className={`routing-status ${event.status}`}>
                    {event.status}
                  </span>
                </header>

                <div className="routing-decision-grid">
                  <div>
                    <span>已选择</span>
                    <strong>{String(selected)}</strong>
                  </div>
                  <div>
                    <span>评分</span>
                    <strong>
                      {numberText(detail.selectedScore ?? detail.adaptive_score, 4)}
                    </strong>
                  </div>
                  <div>
                    <span>模式</span>
                    <strong>{String(detail.mode ?? detail.capability ?? "—")}</strong>
                  </div>
                  <div>
                    <span>是否降级</span>
                    <strong>{detail.degraded === true ? "是" : "否"}</strong>
                  </div>
                </div>

                {reason && <p className="routing-reason">{reason}</p>}

                {typeof detail.intentVersion === "string" && detail.intentVersion && (
                  <div className="routing-candidates">
                    <div className="routing-candidate-row">
                      <div>
                        <strong>ExecutionIntent</strong>
                        <small>{String(detail.intentVersion)}</small>
                      </div>
                      <span>{String(detail.taskType ?? "UNKNOWN")}</span>
                      <span>续接 {String(detail.continuation ?? "NONE")}</span>
                      <span>引用 {String(detail.reference ?? "NONE")}</span>
                      <span>知识 {String(detail.knowledgeDependency ?? "NONE")}</span>
                      <span className={detail.sideEffect === true ? "constraint-bad" : "constraint-good"}>
                        {detail.sideEffect === true ? "副作用" : "无副作用"}
                      </span>
                    </div>
                    {Array.isArray(detail.requiredCapabilities) && detail.requiredCapabilities.length > 0 && (
                      <p className="routing-reason">
                        所需能力：{detail.requiredCapabilities.filter((item): item is string => typeof item === "string").join(", ")}
                      </p>
                    )}
                  </div>
                )}

                {candidates.length > 0 && (
                  <div className="routing-candidates">
                    {candidates.map((candidate, candidateIndex) => {
                      const name =
                        candidate.agentName ??
                        candidate.runtimeId ??
                        candidate.model ??
                        `candidate-${candidateIndex + 1}`;
                      return (
                        <div className="routing-candidate-row" key={`${String(name)}-${candidateIndex}`}>
                          <div>
                            <strong>{String(name)}</strong>
                            <small>
                              {String(candidate.provider ?? candidate.capability ?? "")}
                            </small>
                          </div>
                          <span>Q {numberText(candidate.quality)}</span>
                          <span>R {numberText(candidate.reliability)}</span>
                          <span>{String(candidate.latencyMs ?? "—")} ms</span>
                          <span>成本 {numberText(candidate.avgCost, 5)}</span>
                          <span className={candidate.feasible === false ? "constraint-bad" : "constraint-good"}>
                            {candidate.feasible === false ? "已降级" : "符合"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
