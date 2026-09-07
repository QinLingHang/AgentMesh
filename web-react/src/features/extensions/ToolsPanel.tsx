import { useState } from "react";
import { createTool, deleteTool, seedDemoTools } from "../../api";
import type { Tool } from "../../types";
import { Icon } from "../../components/common/Icon";

// P4 validation contract: 添加 HTTP Tool / app.tools.http_demo_server
export function ToolsPanel({ tools, reload }: { tools: Tool[]; reload: () => Promise<void> }) {
  const [name, setName] = useState("local_http_echo");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:9584/tool/echo");
  const [riskLevel, setRiskLevel] = useState<"low" | "medium" | "high">("low");
  const [requiresConfirmation, setRequiresConfirmation] = useState(false);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);

  return (
    <div className="extension-product-panel">
      <div className="subpage-head calm-subpage-head">
        <div>
          <h2>工具</h2>
          <p>让智能体执行确定性动作，例如查询业务数据、调用内部接口或触发流程。</p>
        </div>
        <div className="calm-head-actions">
          <button
            className="calm-button ghost"
            onClick={async () => {
              await seedDemoTools();
              await reload();
            }}
          >
            添加演示工具
          </button>
          <button className="calm-button primary" type="button" onClick={() => setShowAdd((value) => !value)}>
            <Icon name="plus" size={14} />
            添加工具
          </button>
        </div>
      </div>

      {showAdd && (
        <div className="extension-add-card tool-add-card">
          <label>
            <span>工具名称</span>
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="wide">
            <span>服务地址</span>
            <input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} />
          </label>
          <label>
            <span>风险等级</span>
            <select value={riskLevel} onChange={(event) => setRiskLevel(event.target.value as "low" | "medium" | "high")}>
              <option value="low">低风险 · 可自动执行</option>
              <option value="medium">中风险 · 建议确认</option>
              <option value="high">高风险 · 必须确认</option>
            </select>
          </label>
          <label className="tool-confirm-calm">
            <span>执行前确认</span>
            <input
              type="checkbox"
              checked={requiresConfirmation}
              onChange={(event) => setRequiresConfirmation(event.target.checked)}
            />
          </label>
          <div className="extension-add-actions">
            <button className="calm-button subtle" type="button" onClick={() => setShowAdd(false)}>取消</button>
            <button
              className="calm-button primary"
              type="button"
              onClick={async () => {
                try {
                  setError("");
                  await createTool({
                    name,
                    description: "Local HTTP JSON POST tool",
                    protocol: "http",
                    endpoint,
                    inputSchema: {
                      type: "object",
                      properties: { text: { type: "string" } },
                      additionalProperties: true,
                    },
                    riskLevel,
                    requiresConfirmation: requiresConfirmation || riskLevel === "high",
                    enabled: true,
                  });
                  setShowAdd(false);
                  await reload();
                } catch {
                  setError("工具保存失败，请检查服务地址或稍后重试。");
                }
              }}
            >
              保存工具
            </button>
          </div>
          <details className="developer-note">
            <summary>开发者接入说明</summary>
            <p>本地演示服务：<code>python -m app.tools.http_demo_server</code></p>
          </details>
        </div>
      )}

      {error && <div className="calm-feedback error">{error}</div>}

      <div className="tool-calm-list">
        {tools.length === 0 && (
          <div className="calm-empty-card">
            <Icon name="tool" size={20} />
            <strong>还没有可用工具</strong>
            <span>添加工具后，智能体可以在需要时自动调用。</span>
          </div>
        )}
        {tools.map((tool) => (
          <article className="tool-calm-row" key={tool.id}>
            <span className="extension-calm-icon"><Icon name="tool" size={16} /></span>
            <div className="tool-calm-copy">
              <strong>{tool.name}</strong>
              <small>{tool.description || "暂无描述"}</small>
            </div>
            <span className={`tool-risk-chip risk-${tool.riskLevel}`}>
              {tool.riskLevel === "high" ? "高风险" : tool.riskLevel === "medium" ? "中风险" : "低风险"}
            </span>
            <span className={`calm-status ${tool.enabled ? "ok" : "idle"}`}><i />{tool.enabled ? "可用" : "停用"}</span>
            <details className="connection-technical-detail compact">
              <summary>详情</summary>
              <span>{tool.protocol}</span>
            </details>
            <button
              className="calm-icon-button danger"
              type="button"
              onClick={async () => {
                await deleteTool(tool.id);
                await reload();
              }}
            >
              删除
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}
