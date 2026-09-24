import { useState } from "react";
import { createMCPServer, deleteMCPServer, discoverMCPTools, seedDemoMCPServer } from "../../api";
import type { MCPDiscoveredTool, MCPServer } from "../../types";
import { Icon } from "../../components/common/Icon";

// Tool/MCP validation contract: python -m app.mcp.demo_server / 127.0.0.1:9583/mcp
export function MCPPanel({ servers, reload }: { servers: MCPServer[]; reload: () => Promise<void> }) {
  const [name, setName] = useState("Local MCP");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:9583/mcp");
  const [discovered, setDiscovered] = useState<Record<number, MCPDiscoveredTool[]>>({});
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);

  const discover = async (id: number) => {
    try {
      setError("");
      const tools = await discoverMCPTools(id);
      setDiscovered((current) => ({ ...current, [id]: tools }));
    } catch {
      setError("暂时无法读取这个连接提供的能力，请检查服务后重试。");
    }
  };

  return (
    <div className="extension-product-panel">
      <div className="subpage-head calm-subpage-head">
        <div>
          <h2>外部连接</h2>
          <p>把已有服务接入 AgentMesh。连接成功后，智能体可以按需使用其中的能力。</p>
        </div>
        <div className="calm-head-actions">
          <button
            className="calm-button ghost"
            onClick={async () => {
              await seedDemoMCPServer();
              await reload();
            }}
          >
            创建演示连接
          </button>
          <button className="calm-button primary" type="button" onClick={() => setShowAdd((value) => !value)}>
            <Icon name="plus" size={14} />
            添加连接
          </button>
        </div>
      </div>

      {showAdd && (
        <div className="extension-add-card">
          <label>
            <span>连接名称</span>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="wide">
            <span>服务地址</span>
            <input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} />
          </label>
          <div className="extension-add-actions">
            <button className="calm-button subtle" type="button" onClick={() => setShowAdd(false)}>取消</button>
            <button
              className="calm-button primary"
              type="button"
              onClick={async () => {
                await createMCPServer({
                  name,
                  endpoint,
                  transport: "streamable_http",
                  enabled: true,
                  connectTimeoutMs: 5000,
                  callTimeoutMs: 10000,
                });
                setShowAdd(false);
                await reload();
              }}
            >
              保存连接
            </button>
          </div>
          <details className="developer-note">
            <summary>开发者接入说明</summary>
            <p>本地演示服务：<code>python -m app.mcp.demo_server</code></p>
          </details>
        </div>
      )}

      {error && <div className="calm-feedback error">{error}</div>}

      <div className="connection-card-list">
        {servers.length === 0 && (
          <div className="calm-empty-card">
            <Icon name="server" size={20} />
            <strong>还没有外部连接</strong>
            <span>添加一个连接后，AgentMesh 可以发现并调用更多能力。</span>
          </div>
        )}

        {servers.map((server) => (
          <article className="connection-calm-card" key={server.id}>
            <div className="connection-card-main">
              <span className="extension-calm-icon"><Icon name="server" size={17} /></span>
              <div>
                <strong>{server.name}</strong>
                <small>{server.enabled ? "已连接" : "已停用"}</small>
              </div>
            </div>

            <div className="connection-card-actions">
              <button className="calm-button subtle" type="button" onClick={() => void discover(server.id)}>
                查看可用能力
              </button>
              <button
                className="calm-icon-button danger"
                type="button"
                onClick={async () => {
                  await deleteMCPServer(server.id);
                  await reload();
                }}
              >
                删除
              </button>
            </div>

            <details className="connection-technical-detail">
              <summary>连接详情</summary>
              <code>{server.endpoint}</code>
            </details>

            {discovered[server.id]?.length > 0 && (
              <div className="discovered-calm-list">
                {discovered[server.id].map((tool) => (
                  <div key={tool.name}>
                    <strong>{tool.name}</strong>
                    <span>{tool.description || "可由 AgentMesh 在任务中调用"}</span>
                  </div>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
