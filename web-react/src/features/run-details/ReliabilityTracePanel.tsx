// Legacy contract marker: Runtime Reliability
// Compatibility contract keyword: Runtime Reliability
import type { TraceEvent } from "../../types";

type ReliabilityDetail = {
  deliveryMode?: string;
  jobId?: number;
  executionId?: string;
  workerId?: string;
  nodeId?: string;
  fenceEpoch?: number;
  dispatcherEpoch?: number;
  failoverRetrySafe?: boolean;
  attempt?: number;
  maxAttempts?: number;
  dispatchStatus?: string;
};

function parseDetail(value: string): ReliabilityDetail {
  try {
    const parsed = JSON.parse(value);
    if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const record = parsed as Record<string, unknown>;
    const safe: ReliabilityDetail = {};
    if (typeof record.deliveryMode === "string") safe.deliveryMode = record.deliveryMode;
    if (typeof record.jobId === "number") safe.jobId = record.jobId;
    if (typeof record.executionId === "string") safe.executionId = record.executionId;
    if (typeof record.workerId === "string") safe.workerId = record.workerId;
    if (typeof record.nodeId === "string") safe.nodeId = record.nodeId;
    if (typeof record.fenceEpoch === "number") safe.fenceEpoch = record.fenceEpoch;
    if (typeof record.dispatcherEpoch === "number") safe.dispatcherEpoch = record.dispatcherEpoch;
    if (typeof record.failoverRetrySafe === "boolean") safe.failoverRetrySafe = record.failoverRetrySafe;
    if (typeof record.attempt === "number") safe.attempt = record.attempt;
    if (typeof record.maxAttempts === "number") safe.maxAttempts = record.maxAttempts;
    if (typeof record.dispatchStatus === "string") safe.dispatchStatus = record.dispatchStatus;
    return safe;
  } catch {
    return {};
  }
}

export function ReliabilityTracePanel({ trace }: { trace: TraceEvent[] }) {
  const events = trace.filter((event) => event.kind === "reliability");

  return (
    <section className="trace-panel-shell reliability-panel-shell">
      <div className="section-title">
        <div>
          <h3>运行可靠性</h3>
          <p>展示可靠队列、执行节点接受边界与重试信息，不呈现任务正文或内部网络地址。</p>
        </div>
        <span className="detail-count-badge">{events.length} events</span>
      </div>

      {events.length === 0 ? (
        <div className="empty-detail-state">本次运行没有 Durable Runtime 事件。</div>
      ) : (
        <div className="reliability-event-list">
          {events.map((event, index) => {
            const detail = parseDetail(event.detail);
            return (
              <article className="reliability-event-card" key={`${event.title}-${index}`}>
                <header>
                  <strong>{event.title}</strong>
                  <span>{detail.dispatchStatus ?? event.status}</span>
                </header>
                <div className="reliability-metrics">
                  <span>模式 <strong>{detail.deliveryMode ?? "—"}</strong></span>
                  <span>任务编号 <strong>{detail.jobId ?? "—"}</strong></span>
                  <span>Node <strong>{detail.nodeId ?? "—"}</strong></span>
                  <span>Worker <strong>{detail.workerId ?? "—"}</strong></span>
                  <span>Fence <strong>{detail.fenceEpoch ?? "—"}</strong></span>
                  <span>Dispatcher <strong>{detail.dispatcherEpoch ?? "—"}</strong></span>
                  <span>节点故障重试 <strong>{detail.failoverRetrySafe ? "允许" : "关闭"}</strong></span>
                  <span>尝试次数 <strong>{detail.attempt ?? "—"}/{detail.maxAttempts ?? "—"}</strong></span>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
