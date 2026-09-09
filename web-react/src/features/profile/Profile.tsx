import type {
  Agent,
  Conversation,
  Project,
  Task,
  User,
} from "../../types";
import { Icon } from "../../components/common/Icon";

export function Profile({
  user,
  projects,
  conversations,
  agents,
  tasks,
  onNavigate,
}: {
  user: User;
  projects: Project[];
  conversations: Conversation[];
  agents: Agent[];
  tasks: Task[];
  onNavigate: (page: "workspace" | "model-settings" | "governance") => void;
}) {
  const initials = user.displayName.slice(0, 2).toUpperCase();
  const metrics = [
    { label: "项目", value: projects.length },
    { label: "会话", value: conversations.length },
    { label: "智能体", value: agents.length },
    { label: "任务记录", value: tasks.length },
  ];

  return (
    <div className="page calm-page profile-page">
      <header className="calm-page-head profile-page-head">
        <div className="calm-page-copy">
          <span className="calm-kicker">个人主页</span>
          <h1>你的 AgentMesh 工作概览</h1>
          <p>查看账户信息与个人工作概况，并快速进入常用设置。</p>
        </div>
      </header>

      <section className="profile-identity-card">
        <span className="profile-avatar-large">{initials}</span>
        <div className="profile-identity-copy">
          <h2>{user.displayName}</h2>
          <p>{user.email}</p>
          <span className={`profile-account-state ${user.status === "active" ? "ok" : "idle"}`}>
            <i />
            账户状态：{user.status === "active" ? "正常" : user.status || "未知"}
          </span>
        </div>
      </section>

      <section className="profile-section">
        <div className="profile-section-head">
          <div>
            <span className="calm-kicker">工作概览</span>
            <h2>当前个人空间</h2>
          </div>
        </div>
        <div className="profile-metric-grid">
          {metrics.map((metric) => (
            <article className="profile-metric-card" key={metric.label}>
              <strong>{metric.value}</strong>
              <span>{metric.label}</span>
            </article>
          ))}
        </div>
      </section>

      <section className="profile-section">
        <div className="profile-section-head">
          <div>
            <span className="calm-kicker">常用入口</span>
            <h2>继续你的工作</h2>
          </div>
        </div>
        <div className="profile-shortcut-grid">
          <button type="button" onClick={() => onNavigate("workspace")}>
            <span><Icon name="workspace" size={17} /></span>
            <div>
              <strong>工作台</strong>
              <small>继续最近的会话、项目和任务。</small>
            </div>
          </button>
          <button type="button" onClick={() => onNavigate("model-settings")}>
            <span><Icon name="server" size={17} /></span>
            <div>
              <strong>模型设置</strong>
              <small>管理你的个人模型服务和自动路由。</small>
            </div>
          </button>
          <button type="button" onClick={() => onNavigate("governance")}>
            <span><Icon name="shield" size={17} /></span>
            <div>
              <strong>治理与安全</strong>
              <small>查看组织、权限、配额与安全边界。</small>
            </div>
          </button>
        </div>
      </section>
    </div>
  );
}
