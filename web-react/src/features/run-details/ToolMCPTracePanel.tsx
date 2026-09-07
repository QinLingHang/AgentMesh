import type { TraceEvent } from "../../types";


type RecordValue = Record<string, unknown>;

function parseDetail(detail: string): RecordValue {
  try {
    const value: unknown = JSON.parse(detail);
    return typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as RecordValue)
      : {};
  } catch {
    return {};
  }
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown) {
  return typeof value === "number" ? value : null;
}

export function ToolMCPTracePanel({
  trace,
}: {
  trace: TraceEvent[];
}) {
  const events = trace.filter(
    (event) =>
      event.kind === "tool" ||
      event.kind === "mcp" ||
      event.kind === "approval",
  );

  return (
    <section className="trace-panel-shell">
      <div className="section-title">
        <div>
          <h3>工具与外部服务</h3>
          <p>
            展示工具选择、执行、重试以及 MCP Discovery / Call 的运行元数据；不展开完整业务结果。
          </p>
        </div>
        <span className="detail-count-badge">{events.length} events</span>
      </div>

      {events.length === 0 ? (
        <div className="empty-state compact-empty-state">
          <strong>本次运行没有工具或外部服务事件</strong>
          <p>只有运行环境实际选择或发现外部工具时才会产生这里的事件。</p>
        </div>
      ) : (
        <div className="simple-list tool-mcp-event-list">
          {events.map((event, index) => {
            const detail = parseDetail(event.detail);
            const error =
              typeof detail.error === "object" &&
              detail.error !== null &&
              !Array.isArray(detail.error)
                ? (detail.error as RecordValue)
                : {};

            const tool =
              stringValue(detail.tool) || stringValue(detail.server) || "-";
            const protocol =
              stringValue(detail.protocol) ||
              stringValue(detail.transport) ||
              (event.kind === "approval" ? "human approval" : event.kind);
            const latency =
              numberValue(detail.latency_ms) ?? numberValue(detail.latencyMs);
            const attempt = numberValue(detail.attempt);
            const toolCount =
              numberValue(detail.tool_count) ?? numberValue(detail.toolCount);
            const errorType = stringValue(error.type);

            return (
              <div className="simple-row" key={`${event.title}-${index}`}>
                <div className="simple-main">
                  <strong>{event.title}</strong>
                  <small>
                    {tool} · {protocol}
                    {latency == null ? "" : ` · ${latency} ms`}
                    {attempt == null ? "" : ` · retry ${attempt}`}
                    {toolCount == null ? "" : ` · ${toolCount} tools`}
                    {errorType ? ` · ${errorType}` : ""}
                  </small>
                </div>
                <span className={`status-label ${event.status}`}>{event.status}</span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
