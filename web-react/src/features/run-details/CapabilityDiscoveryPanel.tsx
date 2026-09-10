import type { TraceEvent } from "../../types";

type RecordValue = Record<string, unknown>;

type Candidate = {
  kind: string;
  id: string;
  name: string;
  score: number | null;
  selected: boolean;
  reason: string;
  source: string;
  riskLevel: string;
};

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

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function candidates(value: unknown): Candidate[] {
  if (!Array.isArray(value)) return [];

  return value.flatMap((raw) => {
    if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return [];
    const item = raw as RecordValue;
    return [{
      kind: stringValue(item.kind),
      id: stringValue(item.id),
      name: stringValue(item.name),
      score: numberValue(item.score),
      selected: item.selected === true,
      reason: stringValue(item.reason),
      source: stringValue(item.source),
      riskLevel: stringValue(item.riskLevel),
    }];
  });
}

function kindLabel(kind: string) {
  switch (kind) {
    case "tool":
      return "工具";
    case "mcp_server":
      return "MCP 服务";
    case "mcp_tool":
      return "MCP 工具";
    case "skill":
      return "Skill";
    case "knowledge":
      return "知识";
    default:
      return kind || "能力";
  }
}

export function CapabilityDiscoveryPanel({ trace }: { trace: TraceEvent[] }) {
  const events = trace.filter((event) => event.kind === "capability_discovery");

  return (
    <section
      className="trace-panel-shell capability-discovery-panel"
      data-testid="capability-discovery"
    >
      <div className="section-title">
        <div>
          <h3>能力发现</h3>
          <p>
            展示 AgentMesh 如何根据当前目标自主发现并筛选 Tool、MCP、Skill 与当前会话可用知识库。
            这里只展示选择元数据，不展示工具参数、返回正文或凭据。
          </p>
        </div>
        <span className="detail-count-badge">{events.length} events</span>
      </div>

      {events.length === 0 ? (
        <div className="empty-state compact-empty-state">
          <strong>本次运行没有能力发现事件</strong>
          <p>普通快速对话不会进入能力发现；需要执行、外部服务或知识库时才会产生记录。</p>
        </div>
      ) : (
        <div className="capability-discovery-list">
          {events.map((event, eventIndex) => {
            const detail = parseDetail(event.detail);
            const selectedTools = strings(detail.selectedTools);
            const selectedMcpTools = strings(detail.selectedMCPTools);
            const selectedSkills = strings(detail.selectedSkills);
            const selectedServers = Array.isArray(detail.selectedMCPServers)
              ? detail.selectedMCPServers.map(String)
              : [];
            const knowledgeSelected = detail.knowledgeSelected === true || detail.projectKnowledge === true;
            const contextualized = detail.contextualized === true;
            const historyTurns = numberValue(detail.historyTurns);
            const confidence = numberValue(detail.confidence);
            const items = candidates(detail.candidates);
            const chosen = items.filter((item) => item.selected);
            const rejected = items.filter((item) => !item.selected).slice(0, 8);

            const selectedSummary = [
              ...selectedTools,
              ...selectedMcpTools,
              ...selectedSkills,
              ...selectedServers.map((id) => `MCP #${id}`),
              ...(knowledgeSelected ? ["知识库"] : []),
            ];

            return (
              <article
                className="capability-discovery-event"
                data-testid="capability-discovery-event"
                data-knowledge-selected={knowledgeSelected ? "true" : "false"}
                key={`${event.title}-${eventIndex}`}
              >
                <header>
                  <div>
                    <strong>{event.title}</strong>
                    <small>
                      {confidence == null ? "相关能力动态筛选" : `置信度 ${Math.round(confidence * 100)}%`}
                    </small>
                  </div>
                  <span className={`status-label ${event.status}`}>{event.status}</span>
                </header>

                {contextualized && (
                  <div className="capability-context-note">
                    <strong>承接最近上下文</strong>
                    <span>
                      本轮是简短承接语，能力发现复用了最近
                      {historyTurns == null ? "会话" : ` ${Math.round(historyTurns)} 条会话消息`}
                      来保持上一任务与能力选择连续。
                    </span>
                  </div>
                )}

                <div className="capability-selection-summary">
                  <span>最终选择</span>
                  {selectedSummary.length > 0 ? (
                    <div>
                      {selectedSummary.map((name) => (
                        <code key={name}>{name}</code>
                      ))}
                    </div>
                  ) : (
                    <small>没有能力超过相关性门槛，本轮使用基础模型。</small>
                  )}
                </div>

                {chosen.length > 0 && (
                  <div className="capability-candidate-group">
                    <span>已选候选</span>
                    <div className="capability-candidate-list">
                      {chosen.map((item, index) => (
                        <div
                          className="capability-candidate selected"
                          key={`${item.kind}-${item.id}-${index}`}
                        >
                          <div>
                            <small>{kindLabel(item.kind)}</small>
                            <strong>{item.name || item.id}</strong>
                          </div>
                          <span>{item.score == null ? "—" : item.score.toFixed(2)}</span>
                          <p>
                            {item.reason || "与当前目标相关"}
                            {item.riskLevel ? ` · 风险 ${item.riskLevel}` : ""}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {rejected.length > 0 && (
                  <details className="capability-rejected">
                    <summary>查看未选候选（{items.length - chosen.length}）</summary>
                    <div className="capability-candidate-list">
                      {rejected.map((item, index) => (
                        <div
                          className="capability-candidate"
                          key={`${item.kind}-${item.id}-${index}`}
                        >
                          <div>
                            <small>{kindLabel(item.kind)}</small>
                            <strong>{item.name || item.id}</strong>
                          </div>
                          <span>{item.score == null ? "—" : item.score.toFixed(2)}</span>
                          <p>{item.reason || "相关性不足或被治理过滤"}</p>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
