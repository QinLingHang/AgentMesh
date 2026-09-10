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

function desktopToolName(event: TraceEvent) {
  const detail = parseDetail(event.detail);
  const name = stringValue(detail.tool);
  return name.startsWith("local.") ? name : "";
}

function actionCopy(name: string) {
  if (name.startsWith("local.fs.")) return "本机文件";
  if (name.startsWith("local.app.")) return "本地应用";
  if (name.startsWith("local.tool.")) return "命令行工具";
  if (name.startsWith("local.terminal.")) return "高级终端";
  if (name.startsWith("local.ui.")) return "桌面控制";
  return "本机能力";
}

export function DesktopTracePanel({ trace }: { trace: TraceEvent[] }) {
  const events = trace.filter((event) => Boolean(desktopToolName(event)));

  return (
    <section
      className="trace-panel-shell desktop-trace-panel"
      data-testid="desktop-trace"
    >
      <div className="section-title">
        <div>
          <h3>本机执行</h3>
          <p>
            展示本机文件、应用、CLI 与 Computer Use 的执行元数据。文件正文、截图 Base64、键入文本、终端命令和进程输出不会在这里展开。
          </p>
        </div>
        <span className="detail-count-badge">{events.length} events</span>
      </div>

      {events.length === 0 ? (
        <div className="empty-state compact-empty-state">
          <strong>本次运行没有本机执行事件</strong>
          <p>只有 Agent 实际调用 local.* 官方工具时，这里才会产生记录。</p>
        </div>
      ) : (
        <div className="desktop-trace-list">
          {events.map((event, index) => {
            const detail = parseDetail(event.detail);
            const tool = desktopToolName(event);
            const latency = numberValue(detail.latency_ms) ?? numberValue(detail.latencyMs);
            const risk = stringValue(detail.risk_level) || stringValue(detail.riskLevel);
            const requiresConfirmation = detail.requires_confirmation === true || detail.requiresConfirmation === true;
            const processId = stringValue(detail.processId);

            return (
              <article
                className="desktop-trace-row"
                data-testid="desktop-trace-event"
                data-tool={tool}
                data-status={event.status}
                key={`${event.title}-${index}`}
              >
                <div className="desktop-trace-row-main">
                  <span className="desktop-trace-kind">{actionCopy(tool)}</span>
                  <strong>{event.title}</strong>
                  <small>
                    {tool}
                    {latency == null ? "" : ` · ${latency} ms`}
                    {risk ? ` · ${risk}` : ""}
                    {requiresConfirmation ? " · 需审批" : ""}
                    {processId ? ` · process ${processId.slice(0, 8)}…` : ""}
                  </small>
                </div>
                <span className={`status-label ${event.status}`}>{event.status}</span>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
