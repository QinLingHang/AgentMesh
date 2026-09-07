import { useMemo, useState } from "react";
import { createAgent, seedDemoAgents } from "../../api";
import type { Agent } from "../../types";
import { Icon } from "../../components/common/Icon";
import { formatPercent } from "../../utils/format";
import { AgentDrawer } from "./AgentDrawer";

function agentStatusLabel(status: string) {
  return status === "ACTIVE" ? "可用" : "暂不可用";
}

function agentKindLabel(protocol: string) {
  switch (protocol) {
    case "a2a":
      return "远程智能体";
    case "internal":
    case "langgraph":
      return "平台智能体";
    default:
      return "外部智能体";
  }
}

export function Agents({ agents, reload }: { agents: Agent[]; reload: () => Promise<void> }) {
  const [selected, setSelected] = useState<Agent | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("自定义智能体");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:9999/agent");
  const [protocol, setProtocol] = useState("http");
  const [caps, setCaps] = useState("通用");
  const [query, setQuery] = useState("");

  const visibleAgents = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return agents;
    return agents.filter((agent) =>
      [agent.name, agent.provider, agent.protocol, ...agent.capabilities]
        .join(" ")
        .toLowerCase()
        .includes(normalized),
    );
  }, [agents, query]);

  const activeCount = agents.filter((agent) => agent.status === "ACTIVE").length;

  const add = async () => {
    await createAgent({
      name,
      endpoint,
      protocol,
      capabilities: caps
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean),
      provider: protocol === "a2a" ? "remote" : "external",
      qualityScore: 0.8,
      avgLatencyMs: 1000,
      avgCost: 0.01,
      successRate: 0.95,
      failureRate: 0,
      currentLoad: 0,
    });
    setShowForm(false);
    await reload();
  };

  return (
    <div className="page calm-page agents-calm-page">
      <header className="calm-page-head">
        <div className="calm-page-copy">
          <span className="calm-kicker">AI 团队</span>
          <h1>智能体</h1>
          <p>查看、接入和管理可参与任务协作的 AI 成员。技术参数只在需要时展开。</p>
        </div>

        <div className="calm-head-actions">
          <button
            className="calm-button subtle"
            onClick={async () => {
              await seedDemoAgents();
              await reload();
            }}
          >
            创建演示智能体
          </button>
          <button className="calm-button primary" onClick={() => setShowForm((value) => !value)}>
            <Icon name="plus" size={15} />
            添加智能体
          </button>
        </div>
      </header>

      <section className="calm-overview-strip" aria-label="智能体概览">
        <div>
          <span>全部智能体</span>
          <strong>{agents.length}</strong>
        </div>
        <div>
          <span>当前可用</span>
          <strong>{activeCount}</strong>
        </div>
        <div className="calm-overview-grow">
          <span>协作原则</span>
          <strong>按任务自动选择最合适的成员</strong>
        </div>
      </section>

      {showForm && (
        <section className="calm-editor-card" aria-label="添加智能体">
          <div className="calm-editor-head">
            <div>
              <strong>添加一个智能体</strong>
              <p>常用信息优先；连接协议和服务地址作为高级接入配置保留。</p>
            </div>
            <button className="calm-icon-button" type="button" onClick={() => setShowForm(false)}>
              <Icon name="close" size={15} />
            </button>
          </div>
          <div className="calm-form-grid">
            <label>
              <span>名称</span>
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              <span>接入方式</span>
              <select value={protocol} onChange={(e) => setProtocol(e.target.value)}>
                <option value="http">网页接口（HTTP）</option>
                <option value="a2a">智能体互联（A2A）</option>
                <option value="internal">平台内部</option>
                <option value="langgraph">流程编排（LangGraph）</option>
              </select>
            </label>
            <label className="wide">
              <span>能力标签</span>
              <input
                value={caps}
                onChange={(e) => setCaps(e.target.value)}
                placeholder={protocol === "a2a" ? "可留空，由智能体自动发现" : "例如：数据分析,文档处理"}
              />
            </label>
            <label className="wide advanced-field">
              <span>连接地址</span>
              <input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} />
            </label>
          </div>
          <div className="calm-editor-actions">
            <button className="calm-button subtle" type="button" onClick={() => setShowForm(false)}>
              取消
            </button>
            <button className="calm-button primary" type="button" onClick={() => void add()}>
              保存智能体
            </button>
          </div>
        </section>
      )}

      <div className="calm-toolbar-row">
        <div className="calm-search-field">
          <Icon name="search" size={15} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索智能体或能力…"
            aria-label="搜索智能体"
          />
        </div>
        <span className="calm-result-count">{visibleAgents.length} 个结果</span>
      </div>

      <div className="agent-calm-grid">
        {visibleAgents.map((agent) => (
          <button
            type="button"
            className="agent-calm-card"
            key={agent.id}
            onClick={() => setSelected(agent)}
          >
            <div className="agent-calm-card-head">
              <span className="agent-calm-avatar">
                {agent.name.slice(0, 2).toUpperCase()}
              </span>
              <span className={`calm-status ${agent.status === "ACTIVE" ? "ok" : "idle"}`}>
                <i />
                {agentStatusLabel(agent.status)}
              </span>
            </div>

            <div className="agent-calm-title-block">
              <strong>{agent.name}</strong>
              <span>{agentKindLabel(agent.protocol)}</span>
            </div>

            <div className="agent-calm-tags">
              {agent.capabilities.length > 0 ? (
                agent.capabilities.slice(0, 4).map((capability) => <span key={capability}>{capability}</span>)
              ) : (
                <span>能力自动发现</span>
              )}
            </div>

            <div className="agent-calm-metrics">
              <div>
                <span>质量</span>
                <strong>{Math.round(agent.qualityScore * 100)}</strong>
              </div>
              <div>
                <span>成功率</span>
                <strong>{formatPercent(agent.successRate)}</strong>
              </div>
              <div>
                <span>平均耗时</span>
                <strong>{agent.avgLatencyMs < 1000 ? `${agent.avgLatencyMs}ms` : `${(agent.avgLatencyMs / 1000).toFixed(1)}s`}</strong>
              </div>
              <div>
                <span>协作状态</span>
                <strong>{agent.currentLoad > 0 ? "处理中" : "空闲"}</strong>
              </div>
            </div>

            <div className="agent-calm-footer">
              <span>查看详情与高级配置</span>
              <Icon name="arrow" size={14} />
            </div>
          </button>
        ))}
      </div>

      {visibleAgents.length === 0 && (
        <div className="calm-empty-card">
          <Icon name="agents" size={20} />
          <strong>没有找到匹配的智能体</strong>
          <span>换个关键词试试，或添加一个新的智能体。</span>
        </div>
      )}

      {selected && <AgentDrawer agent={selected} close={() => setSelected(null)} />}
    </div>
  );
}
