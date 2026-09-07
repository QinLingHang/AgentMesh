// Compatibility contract keywords: Project Model Provider | 审计日志 | OWNER ADMIN DEVELOPER VIEWER
import { FormEvent, useEffect, useMemo, useState } from "react";
import type { GovernanceOverview, Organization, Project, ProjectModelProvider, ProjectQuota } from "../../types";
import {
  addOrganizationMember,
  addProjectMember,
  bindOrganizationProject,
  createOrganization,
  createProjectSecret,
  deleteProjectSecret,
  ApiError,
  friendlyApiError,
  getProjectGovernance,
  listOrganizations,
  removeProjectMember,
  updateProjectQuota,
  upsertProjectModelProvider,
} from "../../api";
import { Icon } from "../../components/common/Icon";


function projectRoleLabel(role: string) {
  switch (role) {
    case "OWNER": return "所有者";
    case "ADMIN": return "管理员";
    case "DEVELOPER": return "开发成员";
    case "VIEWER": return "只读成员";
    default: return role;
  }
}

function auditResultLabel(result: string) {
  switch (result.toUpperCase()) {
    case "SUCCESS": return "成功";
    case "FAILED":
    case "FAILURE": return "失败";
    case "DENIED": return "已拒绝";
    default: return result;
  }
}

// Validation vocabulary retained for P9 compatibility; the visible UI uses calmer product wording.
// 审计日志 · 添加组织成员 · 绑定当前 Project 到组织
export function Governance({ projects }: { projects: Project[] }) {
  const [projectId, setProjectId] = useState<number | null>(projects[0]?.id ?? null);
  const [data, setData] = useState<GovernanceOverview | null>(null);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const [memberEmail, setMemberEmail] = useState("");
  const [memberRole, setMemberRole] = useState("DEVELOPER");
  const [secretName, setSecretName] = useState("OPENAI_API_KEY");
  const [secretValue, setSecretValue] = useState("");
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [organizationName, setOrganizationName] = useState("");
  const [organizationId, setOrganizationId] = useState<number | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);

  useEffect(() => {
    if (!projectId || projects.some((project) => project.id === projectId)) return;
    setProjectId(projects[0]?.id ?? null);
  }, [projects, projectId]);

  useEffect(() => {
    // 团队确认是“当前项目”维度的状态，切换项目后不能沿用上一个项目的选择。
    setOrganizationId(null);
    setWarning("");
  }, [projectId]);

  const canAdmin = data?.role === "OWNER" || data?.role === "ADMIN";
  const selectedProject = useMemo(() => projects.find((project) => project.id === projectId) ?? null, [projects, projectId]);
  const selectedOrganization = useMemo(
    () => organizations.find((organization) => organization.id === organizationId) ?? null,
    [organizations, organizationId],
  );

  async function reload(id = projectId) {
    if (!id) {
      setData(null);
      return;
    }
    setLoading(true);
    setError("");
    setWarning("");
    setSuccess("");
    try {
      setData(await getProjectGovernance(id));
    } catch (e) {
      setError(friendlyApiError(e, "治理配置暂时无法读取，请稍后重试。"));
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload(projectId);
  }, [projectId]);

  useEffect(() => {
    void listOrganizations().then(setOrganizations).catch(() => setOrganizations([]));
  }, []);

  async function onCreateOrganization(e: FormEvent) {
    e.preventDefault();
    const name = organizationName.trim();
    if (!name) return;
    try {
      const created = await createOrganization(name);
      setOrganizations((items) => [created, ...items]);
      setOrganizationName("");
      setError("");
      setWarning("");
      setSuccess(`已创建「${created.name}」。如需让当前项目加入该团队，点击上方团队名称即可。`);
    } catch (e) {
      setWarning("");
      setError(friendlyApiError(e, "创建工作空间失败，请稍后重试。"));
    }
  }

  async function onSelectOrganization(organization: Organization) {
    if (!projectId) return;
    setError("");
    setWarning("");
    setSuccess("");
    try {
      await bindOrganizationProject(organization.id, projectId);
      setOrganizationId(organization.id);
      setSuccess(`当前项目已加入「${organization.name}」。后续邀请成员只需填写一次邮箱。`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.code === 40930) {
        setError("");
        setWarning(
          `当前没有发生故障：只是「${selectedProject?.name ?? "当前项目"}」已经属于另一个团队，` +
          `所以不能再加入「${organization.name}」。一个项目同时只能属于一个团队。` +
          "如果你只是想给当前项目添加成员，直接使用“当前项目访问权限”即可；如确实要更换团队，需要先完成项目迁移。",
        );
        return;
      }
      if (e instanceof ApiError && e.status === 403) {
        setWarning("");
        setError("只有团队管理员并且同时是项目所有者的人，才能设置当前项目所属团队。");
        return;
      }
      setWarning("");
      setError(friendlyApiError(e, "设置项目所属团队失败，请稍后重试。"));
    }
  }

  async function onAddMember(e: FormEvent) {
    e.preventDefault();
    const email = memberEmail.trim();
    if (!projectId || !email) return;
    setError("");
    setWarning("");
    setSuccess("");
    try {
      // 已确认当前项目所属团队时，一次邀请同时完成团队成员与项目权限设置。
      // 用户只需要输入一次邮箱，底层仍保留 Organization / Project 两层治理模型。
      if (organizationId) {
        await addOrganizationMember(organizationId, email, memberRole);
      }
      await addProjectMember(projectId, email, memberRole);
      setMemberEmail("");
      await reload();
      setSuccess(
        organizationId && selectedOrganization
          ? `已邀请 ${email} 加入「${selectedOrganization.name}」，并授予当前项目${projectRoleLabel(memberRole)}权限。`
          : `已为 ${email} 授予当前项目${projectRoleLabel(memberRole)}权限。`,
      );
    } catch (e) {
      setError(friendlyApiError(e, "邀请成员失败，请稍后重试。"));
    }
  }

  async function onCreateSecret(e: FormEvent) {
    e.preventDefault();
    if (!projectId || !secretValue) return;
    try {
      await createProjectSecret(projectId, secretName, "MODEL_API_KEY", secretValue);
      setSecretValue("");
      await reload();
    } catch (e) {
      setError(friendlyApiError(e, "保存密钥失败，请稍后重试。"));
    }
  }

  async function onQuotaChange(key: keyof ProjectQuota, value: number) {
    if (!projectId || !data) return;
    const next = { ...data.quota, [key]: value };
    try {
      await updateProjectQuota(projectId, next);
      await reload();
    } catch (e) {
      setError(friendlyApiError(e, "更新额度失败，请稍后重试。"));
    }
  }

  async function saveProvider(provider: ProjectModelProvider) {
    if (!projectId) return;
    try {
      await upsertProjectModelProvider(projectId, provider);
      await reload();
    } catch (e) {
      setError(friendlyApiError(e, "保存模型配置失败，请稍后重试。"));
    }
  }

  return (
    <section className="governance-page calm-page governance-calm-page">
      <header className="calm-page-head governance-calm-head">
        <div className="calm-page-copy">
          <span className="calm-kicker">团队与安全</span>
          <h1>治理与安全</h1>
          <p>管理成员、权限和项目使用边界。密钥、模型与审计记录默认收进高级设置。</p>
        </div>
        <label className="calm-project-picker">
          <span>当前项目</span>
          <select value={projectId ?? ""} onChange={(e) => setProjectId(Number(e.target.value) || null)}>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
      </header>

      {!selectedProject && <div className="calm-empty-card large">请先创建一个项目。</div>}
      {loading && <div className="calm-loading-card">正在读取项目设置…</div>}
      {error && <div className="calm-feedback error">{error}</div>}
      {warning && <div className="calm-feedback warning">{warning}</div>}
      {success && <div className="calm-feedback success">{success}</div>}

      {data && (
        <>
          <section className="calm-overview-strip governance-usage-strip" aria-label="项目使用概览">
            <div>
              <span>你的角色</span>
              <strong>{projectRoleLabel(data.role)}</strong>
            </div>
            <div>
              <span>并发使用</span>
              <strong>{data.usage.concurrentTasks} / {data.quota.concurrentTasks}</strong>
            </div>
            <div>
              <span>本月模型用量</span>
              <strong>{data.usage.tokenCount.toLocaleString()}</strong>
              <small>上限 {data.quota.monthlyTokenLimit.toLocaleString()}</small>
            </div>
            <div>
              <span>本月成本</span>
              <strong>${data.usage.estimatedCost.toFixed(2)}</strong>
              <small>上限 ${data.quota.monthlyCostLimit.toFixed(2)}</small>
            </div>
          </section>

          <div className="governance-calm-grid primary-grid">
            <article className="governance-calm-card organization-card" data-testid="organization-section">
              <div className="governance-calm-card-head">
                <span className="governance-calm-icon"><Icon name="workspace" size={17} /></span>
                <div>
                  <h2>团队协作</h2>
                  <p>团队用来统一管理项目和成员。一个项目同时只属于一个团队，不再需要单独执行“关联项目”。</p>
                </div>
              </div>

              <div className="organization-strip" aria-label="选择当前项目所属团队">
                {organizations.length === 0 ? (
                  <span className="muted">还没有团队工作空间，可以先创建一个。</span>
                ) : (
                  organizations.map((org) => (
                    <button
                      type="button"
                      data-testid="organization-chip"
                      className={`organization-chip${organizationId === org.id ? " active" : ""}`}
                      key={org.id}
                      onClick={() => void onSelectOrganization(org)}
                      title={`将当前项目设置到「${org.name}」`}
                    >
                      {org.name}<small>#{org.id}</small>
                    </button>
                  ))
                )}
              </div>

              <div
                className={`project-team-status${selectedOrganization ? " confirmed" : ""}`}
                data-testid={selectedOrganization ? "project-team-confirmed" : "project-team-unconfirmed"}
              >
                <span className="project-team-status-icon"><Icon name={selectedOrganization ? "check" : "workspace"} size={15} /></span>
                <span>
                  <strong>
                    {selectedOrganization
                      ? `当前项目团队：${selectedOrganization.name}`
                      : "当前项目所属团队尚未在本页确认"}
                  </strong>
                  <small>
                    {selectedOrganization
                      ? "邀请成员时会同时加入团队并授予当前项目权限，不需要重复填写邮箱。"
                      : "如果项目已经属于某个团队，点击对应团队名称即可确认；选择其他团队不会自动迁移项目。"}
                  </small>
                </span>
              </div>

              <form
                className="inline-form organization-form calm-inline-form"
                data-testid="organization-create-form"
                onSubmit={onCreateOrganization}
              >
                <input
                  data-testid="organization-name-input"
                  value={organizationName}
                  onChange={(e) => setOrganizationName(e.target.value)}
                  placeholder="新建团队工作空间"
                />
                <button type="submit" data-testid="organization-create-submit" className="calm-button primary">创建团队</button>
              </form>
            </article>

            <article className="governance-calm-card">
              <div className="governance-calm-card-head">
                <span className="governance-calm-icon"><Icon name="agents" size={17} /></span>
                <div>
                  <h2>当前项目访问权限</h2>
                  <p>这里只管理“谁能使用当前项目”。团队成员和项目权限通过一次邀请完成，不再重复录入邮箱。</p>
                </div>
              </div>

              <div className="governance-member-list">
                {data.members.length === 0 && <p className="muted">暂无额外成员。项目所有者始终拥有最高权限。</p>}
                {data.members.map((member) => (
                  <div className="governance-member-row" key={member.userId}>
                    <span className="governance-member-avatar">{(member.displayName || member.email || "?").slice(0, 1).toUpperCase()}</span>
                    <span className="governance-member-copy">
                      <strong>{member.displayName || member.email}</strong>
                      <small>{member.email}</small>
                    </span>
                    <span className="governance-role-chip">{projectRoleLabel(member.role)}</span>
                    {canAdmin && (
                      <button className="calm-icon-button danger" type="button" onClick={async () => { await removeProjectMember(projectId!, member.userId); await reload(); }}>
                        移除
                      </button>
                    )}
                  </div>
                ))}
              </div>

              {canAdmin && (
                <>
                  <form className="inline-form calm-inline-form three" data-testid="project-member-form" onSubmit={onAddMember}>
                    <input
                      data-testid="project-member-email"
                      type="email"
                      placeholder="成员邮箱（只填一次）"
                      value={memberEmail}
                      onChange={(e) => setMemberEmail(e.target.value)}
                      required
                    />
                    <select data-testid="project-member-role" value={memberRole} onChange={(e) => setMemberRole(e.target.value)}>
                      <option value="ADMIN">管理员</option><option value="DEVELOPER">开发成员</option><option value="VIEWER">只读成员</option>
                    </select>
                    <button type="submit" data-testid="project-member-submit" className="calm-button subtle">邀请成员</button>
                  </form>
                  <p className="governance-form-hint">
                    {selectedOrganization
                      ? `将同步加入「${selectedOrganization.name}」并获得当前项目权限。`
                      : "尚未确认项目所属团队，因此本次只授予当前项目权限。"}
                  </p>
                </>
              )}
            </article>

            <article className="governance-calm-card governance-quota-card">
              <div className="governance-calm-card-head">
                <span className="governance-calm-icon"><Icon name="chart" size={17} /></span>
                <div>
                  <h2>项目额度</h2>
                  <p>限制高频或高成本执行，避免意外消耗。</p>
                </div>
              </div>
              <div className="quota-calm-grid">
                {[
                  ["requestsPerMinute", "每分钟请求"],
                  ["concurrentTasks", "并发任务"],
                  ["monthlyTokenLimit", "每月模型用量"],
                  ["monthlyCostLimit", "每月成本 ($)"],
                  ["dailyToolActionLimit", "每日工具调用"],
                ].map(([key, label]) => (
                  <label className="quota-calm-field" key={key}>
                    <span>{label}</span>
                    <input
                      disabled={!canAdmin}
                      type="number"
                      min="0"
                      value={String(data.quota[key as keyof ProjectQuota])}
                      onChange={(e) => setData({ ...data, quota: { ...data.quota, [key]: Number(e.target.value) } })}
                      onBlur={(e) => void onQuotaChange(key as keyof ProjectQuota, Number(e.target.value))}
                    />
                  </label>
                ))}
              </div>
            </article>
          </div>

          <section className="governance-advanced-section">
            <button type="button" className="governance-section-toggle" onClick={() => setAdvancedOpen((value) => !value)}>
              <span>
                <Icon name="shield" size={16} />
                <strong>高级安全与模型设置</strong>
                <small>项目密钥、自带模型密钥与模型服务</small>
              </span>
              <Icon name="chevron" size={14} />
            </button>

            {advancedOpen && (
              <div className="governance-calm-grid advanced-grid">
                <article className="governance-calm-card">
                  <div className="governance-calm-card-head compact">
                    <span className="governance-calm-icon"><Icon name="shield" size={17} /></span>
                    <div><h2>项目密钥</h2><p>保存后只显示掩码，不会再次把明文返回浏览器。</p></div>
                  </div>
                  {data.secrets.map((secret) => (
                    <div className="governance-secret-row" key={secret.id}>
                      <span><strong>{secret.name}</strong><small>{secret.kind}</small></span>
                      <code>{secret.maskedHint}</code>
                      {canAdmin && <button className="calm-icon-button danger" type="button" onClick={async () => { await deleteProjectSecret(projectId!, secret.id); await reload(); }}>删除</button>}
                    </div>
                  ))}
                  {canAdmin && (
                    <form className="secret-form calm-secret-form" onSubmit={onCreateSecret}>
                      <input value={secretName} onChange={(e) => setSecretName(e.target.value)} placeholder="密钥名称" />
                      <input type="password" autoComplete="new-password" value={secretValue} onChange={(e) => setSecretValue(e.target.value)} placeholder="粘贴密钥（保存后不可读取）" />
                      <button type="submit" className="calm-button primary">安全保存</button>
                    </form>
                  )}
                </article>

                <ProviderCard projectId={projectId!} data={data} canAdmin={!!canAdmin} onSave={saveProvider} />
              </div>
            )}
          </section>

          {canAdmin && (
            <section className="governance-advanced-section">
              <button type="button" className="governance-section-toggle" onClick={() => setAuditOpen((value) => !value)}>
                <span>
                  <Icon name="activity" size={16} />
                  <strong>审计记录</strong>
                  <small>{data.audit.length} 条最近事件 · 谁操作 / 做了什么 / 结果</small>
                </span>
                <Icon name="chevron" size={14} />
              </button>
              {auditOpen && (
                <article className="governance-calm-card audit-card">
                  <div className="audit-calm-list">
                    {data.audit.length === 0 && <p className="muted">暂无审计事件。</p>}
                    {data.audit.map((event) => (
                      <div className="audit-calm-row" key={event.id}>
                        <time>{new Date(event.createdAt).toLocaleString()}</time>
                        <span className="audit-actor">用户 #{event.actorUserId}</span>
                        <code>{event.action}</code>
                        <span>{event.resourceType}{event.resourceId ? ` · ${event.resourceId}` : ""}</span>
                        <strong>{auditResultLabel(event.result)}</strong>
                      </div>
                    ))}
                  </div>
                </article>
              )}
            </section>
          )}
        </>
      )}
    </section>
  );
}

function ProviderCard({
  projectId,
  data,
  canAdmin,
  onSave,
}: {
  projectId: number;
  data: GovernanceOverview;
  canAdmin: boolean;
  onSave: (provider: ProjectModelProvider) => Promise<void>;
}) {
  const initial = data.modelProvider ?? {
    projectId,
    provider: "openai-compatible",
    baseUrl: "https://api.openai.com/v1",
    modelName: "gpt-4.1-mini",
    secretId: data.secrets[0]?.id ?? null,
    enabled: true,
  };
  const [value, setValue] = useState<ProjectModelProvider>(initial);
  useEffect(() => setValue(initial), [data.modelProvider?.updatedAt, projectId, data.secrets.length]);

  return (
    <article className="governance-calm-card">
      <div className="governance-calm-card-head compact">
        <span className="governance-calm-icon"><Icon name="server" size={17} /></span>
        <div><h2>项目模型服务</h2><p>为当前项目指定模型服务，密钥只通过内部安全通道使用。</p></div>
      </div>
      <div className="provider-calm-grid">
        <label><span>服务类型</span><input disabled={!canAdmin} value={value.provider} onChange={(e) => setValue({ ...value, provider: e.target.value })} /></label>
        <label><span>接口地址</span><input disabled={!canAdmin} value={value.baseUrl} onChange={(e) => setValue({ ...value, baseUrl: e.target.value })} /></label>
        <label><span>模型名称</span><input disabled={!canAdmin} value={value.modelName} onChange={(e) => setValue({ ...value, modelName: e.target.value })} /></label>
        <label><span>关联密钥</span><select disabled={!canAdmin} value={value.secretId ?? ""} onChange={(e) => setValue({ ...value, secretId: Number(e.target.value) || null })}><option value="">不绑定</option>{data.secrets.map((secret) => <option key={secret.id} value={secret.id}>{secret.name} · {secret.maskedHint}</option>)}</select></label>
      </div>
      {canAdmin && <div className="governance-card-actions"><button className="calm-button primary" type="button" onClick={() => void onSave(value)}>保存模型配置</button></div>}
    </article>
  );
}
