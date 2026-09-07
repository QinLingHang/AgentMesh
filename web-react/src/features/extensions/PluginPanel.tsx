import type { PluginInfo } from "../../types";
import { Icon } from "../../components/common/Icon";

export function PluginPanel({ plugins }: { plugins: PluginInfo[] }) {
  return (
    <div className="extension-product-panel">
      <div className="subpage-head calm-subpage-head">
        <div>
          <h2>平台能力</h2>
          <p>这些能力由 AgentMesh 运行环境自动提供，一般不需要你手动配置。</p>
        </div>
      </div>

      <div className="plugin-calm-grid">
        {plugins.length === 0 && (
          <div className="calm-empty-card">
            <Icon name="extensions" size={20} />
            <strong>暂无平台扩展</strong>
            <span>运行环境加载扩展后会自动显示在这里。</span>
          </div>
        )}
        {plugins.map((plugin) => (
          <article className="plugin-calm-card" key={plugin.id}>
            <span className="extension-calm-icon"><Icon name="extensions" size={17} /></span>
            <div className="plugin-calm-copy">
              <strong>{plugin.name}</strong>
              <small>{plugin.provider || "AgentMesh"}</small>
            </div>
            <span className="calm-status ok"><i />可用</span>
            <details className="connection-technical-detail compact">
              <summary>版本</summary>
              <span>{plugin.kind} · v{plugin.version} · {plugin.status}</span>
            </details>
          </article>
        ))}
      </div>
    </div>
  );
}
