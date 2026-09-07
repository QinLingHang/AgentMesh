import { useState } from "react";
import type { MCPServer, PluginInfo, Tool } from "../../types";
import { Icon } from "../../components/common/Icon";
import { MCPPanel } from "./MCPPanel";
import { ToolsPanel } from "./ToolsPanel";
import { PluginPanel } from "./PluginPanel";

type ExtensionTab = "mcp" | "tools" | "plugins";

const TAB_COPY: Record<ExtensionTab, { title: string; description: string; icon: "server" | "tool" | "sparkles" }> = {
  mcp: {
    title: "连接器",
    description: "连接外部服务，让 AgentMesh 能调用更多真实世界能力。",
    icon: "server",
  },
  tools: {
    title: "工具",
    description: "管理可被智能体调用的确定性动作与业务能力。",
    icon: "tool",
  },
  plugins: {
    title: "平台能力",
    description: "查看当前 Runtime 已启用的平台扩展。",
    icon: "sparkles",
  },
};

export function Extensions({
  plugins,
  tools,
  mcpServers,
  reloadTools,
  reloadMCP,
}: {
  plugins: PluginInfo[];
  tools: Tool[];
  mcpServers: MCPServer[];
  reloadTools: () => Promise<void>;
  reloadMCP: () => Promise<void>;
}) {
  const [active, setActive] = useState<ExtensionTab>("mcp");

  const counts: Record<ExtensionTab, number> = {
    mcp: mcpServers.length,
    tools: tools.length,
    plugins: plugins.length,
  };

  return (
    <div className="page calm-page extensions-calm-page">
      <header className="calm-page-head">
        <div className="calm-page-copy">
          <span className="calm-kicker">能力中心</span>
          <h1>让 AgentMesh 做得更多</h1>
          <p>把外部连接、工具和平台扩展集中在一个地方。默认只展示你真正需要管理的内容。</p>
        </div>
      </header>

      <section className="extension-calm-selector" aria-label="能力分类">
        {(Object.keys(TAB_COPY) as ExtensionTab[]).map((tab) => {
          const copy = TAB_COPY[tab];
          return (
            <button
              type="button"
              key={tab}
              className={`extension-calm-tab ${active === tab ? "active" : ""}`}
              onClick={() => setActive(tab)}
            >
              <span className="extension-calm-icon">
                <Icon name={copy.icon} size={18} />
              </span>
              <span className="extension-calm-copy">
                <strong>{copy.title}</strong>
                <small>{copy.description}</small>
              </span>
              <span className="extension-calm-count">{counts[tab]}</span>
            </button>
          );
        })}
      </section>

      <section className="extension-calm-content">
        <div className="extension-calm-content-head">
          <div>
            <span className="calm-kicker">{TAB_COPY[active].title}</span>
            <h2>{TAB_COPY[active].description}</h2>
          </div>
          <span className="calm-status ok"><i />{counts[active]} 项可用</span>
        </div>

        <div className="extension-panel-surface">
          {active === "mcp" && <MCPPanel servers={mcpServers} reload={reloadMCP} />}
          {active === "tools" && <ToolsPanel tools={tools} reload={reloadTools} />}
          {active === "plugins" && <PluginPanel plugins={plugins} />}
        </div>
      </section>
    </div>
  );
}
