import {
  useMemo,
  useState,
} from "react";
import type {
  Agent,
  Conversation,
  MCPServer,
  Project,
  Task,
  Tool,
} from "../../types";
import {
  Icon,
} from "../../components/common/Icon";
import {
  RuntimeStatusBadge,
} from "../../components/common/RuntimeStatusBadge";
import {
  formatDate,
} from "../../utils/format";
import {
  ProjectKnowledge,
} from "./ProjectKnowledge";
import type {
  ProjectKnowledgeStats,
} from "./ProjectKnowledge";
import {
  ProjectGlobalKnowledgeBindings,
} from "./ProjectGlobalKnowledgeBindings";
import {
  ProjectRuntimePanel,
} from "./ProjectRuntimePanel";
import type {
  ProjectRuntimeSummary,
} from "./ProjectRuntimePanel";

function isActiveTask(
  task: Task,
) {
  return [
    "RUNNING",
    "INPUT_REQUIRED",
    "AUTH_REQUIRED",
  ].includes(
    String(
      task.status,
    ).toUpperCase(),
  );
}

export function ProjectHome({
  project,
  conversations,
  tasks,
  agents,
  pluginCount,
  tools,
  mcpServers,
  onOpenConversation,
  onCreateConversation,
  onUpdateProject,
}: {
  project: Project;
  conversations: Conversation[];
  tasks: Task[];
  agents: Agent[];
  pluginCount: number;
  tools: Tool[];
  mcpServers: MCPServer[];
  onOpenConversation: (
    conversation: Conversation,
  ) => void;
  onCreateConversation: () => Promise<void>;
  onUpdateProject: (
    projectId: number,
    name: string,
    description: string,
  ) => Promise<Project>;
}) {
  const [
    creating,
    setCreating,
  ] =
    useState(false);

  const [
    createError,
    setCreateError,
  ] =
    useState("");

  const [
    knowledgeStats,
    setKnowledgeStats,
  ] =
    useState<ProjectKnowledgeStats>({
      total: 0,
      ready: 0,
      pending: 0,
      error: 0,
    });

  const [
    runtimeSummary,
    setRuntimeSummary,
  ] =
    useState<ProjectRuntimeSummary>({
      agentMode: "all",
      agentCount: agents.length,
      toolMode: "all",
      toolCount: tools.filter(
        (tool) => tool.enabled,
      ).length,
      mcpMode: "all",
      mcpCount: mcpServers.filter(
        (server) => server.enabled,
      ).length,
      policyMode: "inherit",
      scheduler: "adaptive",
      planner: "multi_objective",
      executionMode: "auto",
    });

  const [
    editing,
    setEditing,
  ] =
    useState(false);

  const [
    editName,
    setEditName,
  ] =
    useState(
      project.name,
    );

  const [
    editDescription,
    setEditDescription,
  ] =
    useState(
      project.description,
    );

  const [
    editBusy,
    setEditBusy,
  ] =
    useState(false);

  const [
    editError,
    setEditError,
  ] =
    useState("");

  const projectConversationIds =
    useMemo(
      () =>
        new Set(
          project.conversationIds,
        ),
      [
        project.conversationIds,
      ],
    );

  const projectTasks =
    useMemo(
      () =>
        tasks.filter(
          (task) => {
            const conversationId =
              task.conversationId;

            return (
              conversationId != null &&
              projectConversationIds.has(
                conversationId,
              )
            );
          },
        ),
      [
        tasks,
        projectConversationIds,
      ],
    );

  const activeTaskCount =
    projectTasks.filter(
      isActiveTask,
    ).length;

  const completedTaskCount =
    projectTasks.filter(
      (task) =>
        String(
          task.status,
        ).toUpperCase() ===
        "COMPLETED",
    ).length;

  const recentTasks =
    projectTasks.slice(
      0,
      4,
    );

  const recentConversations =
    conversations.slice(
      0,
      6,
    );

  const createConversation =
    async () => {
      try {
        setCreating(true);
        setCreateError("");

        await onCreateConversation();
      } catch (error) {
        setCreateError(
          error instanceof Error
            ? error.message
            : "创建项目会话失败，请稍后重试。",
        );
      } finally {
        setCreating(false);
      }
    };

  const openEdit = () => {
    setEditName(
      project.name,
    );

    setEditDescription(
      project.description,
    );

    setEditError("");

    setEditing(true);
  };

  const saveEdit =
    async () => {
      const name =
        editName.trim();

      if (!name) {
        setEditError(
          "项目名称不能为空。",
        );

        return;
      }

      try {
        setEditBusy(true);
        setEditError("");

        await onUpdateProject(
          project.id,
          name,
          editDescription.trim(),
        );

        setEditing(false);
      } catch (error) {
        setEditError(
          error instanceof Error
            ? error.message
            : "保存失败，请稍后重试。",
        );
      } finally {
        setEditBusy(false);
      }
    };

  return (
    <section className="project-home">
      <header className="project-home-hero">
        <div className="project-home-identity">
          <div className="project-home-icon">
            <Icon
              name="workspace"
              size={19}
            />
          </div>

          <div>
            <div className="eyebrow">
              PROJECT WORKSPACE
            </div>

            <h1>
              {project.name}
            </h1>

            <p>
              {project.description ||
                "集中管理这个项目里的会话、执行记录和 Agent 运行资源。"}
            </p>
          </div>
        </div>

        <div className="project-home-actions">
          <button
            type="button"
            className="secondary-button"
            onClick={
              openEdit
            }
          >
            编辑项目
          </button>

          <button
            type="button"
            className="primary-button project-create-conversation"
            disabled={creating}
            onClick={() =>
              void createConversation()
            }
          >
            <Icon
              name="plus"
              size={14}
            />

            {creating
              ? "创建中..."
              : "新建会话"}
          </button>
        </div>
      </header>

      {createError && (
        <div
          className="project-home-create-error"
          role="alert"
        >
          <span>{createError}</span>

          <button
            type="button"
            onClick={() =>
              setCreateError("")
            }
          >
            <Icon
              name="close"
              size={13}
            />
          </button>
        </div>
      )}

      <div className="project-overview-grid">
        <article className="project-stat-card">
          <span>
            会话
          </span>

          <strong>
            {conversations.length}
          </strong>

          <small>
            项目内长期上下文
          </small>
        </article>

        <article className="project-stat-card">
          <span>
            任务执行
          </span>

          <strong>
            {projectTasks.length}
          </strong>

          <small>
            {completedTaskCount}
            {" "}
            已完成
          </small>
        </article>

        <article className="project-stat-card">
          <span>
            活跃任务
          </span>

          <strong>
            {activeTaskCount}
          </strong>

          <small>
            运行中 / 等待继续
          </small>
        </article>

        <article className="project-stat-card">
          <span>
            最近更新
          </span>

          <strong className="project-stat-date">
            {formatDate(
              project.updatedAt,
            )}
          </strong>

          <small>
            项目活动时间
          </small>
        </article>
      </div>

      <div className="project-home-columns">
        <section className="project-home-panel">
          <header className="project-panel-head">
            <div>
              <h2>
                最近会话
              </h2>

              <p>
                继续项目中的上下文工作。
              </p>
            </div>

            <button
              type="button"
              className="project-panel-action"
              onClick={() =>
                void createConversation()
              }
            >
              <Icon
                name="plus"
                size={13}
              />

              新建
            </button>
          </header>

          {recentConversations.length ===
          0 ? (
            <div className="project-panel-empty">
              <div>
                <Icon
                  name="workspace"
                  size={20}
                />
              </div>

              <strong>
                这个项目还没有会话
              </strong>

              <p>
                创建第一条会话后，它会自动保存在当前项目中。
              </p>

              <button
                type="button"
                onClick={() =>
                  void createConversation()
                }
              >
                创建第一条会话
              </button>
            </div>
          ) : (
            <div className="project-conversation-list">
              {recentConversations.map(
                (conversation) => (
                  <button
                    type="button"
                    className="project-conversation-row"
                    key={
                      conversation.id
                    }
                    onClick={() =>
                      onOpenConversation(
                        conversation,
                      )
                    }
                  >
                    <span className="project-conversation-icon">
                      <Icon
                        name="workspace"
                        size={14}
                      />
                    </span>

                    <span className="project-conversation-copy">
                      <strong>
                        {conversation.title}
                      </strong>

                      <small>
                        {formatDate(
                          conversation.updatedAt,
                        )}
                      </small>
                    </span>

                    <Icon
                      name="arrow"
                      size={14}
                    />
                  </button>
                ),
              )}
            </div>
          )}
        </section>

        <section className="project-home-panel">
          <header className="project-panel-head">
            <div>
              <h2>
                最近执行
              </h2>

              <p>
                项目会话产生的运行任务。
              </p>
            </div>
          </header>

          {recentTasks.length ===
          0 ? (
            <div className="project-runtime-empty">
              暂无项目执行记录。
            </div>
          ) : (
            <div className="project-task-list">
              {recentTasks.map(
                (task) => (
                  <div
                    className="project-task-row"
                    key={task.id}
                  >
                    <div>
                      <strong>
                        Task #{task.id}
                      </strong>

                      <small>
                        {task.taskText}
                      </small>
                    </div>

                    <RuntimeStatusBadge
                      status={
                        task.status
                      }
                    />
                  </div>
                ),
              )}
            </div>
          )}
        </section>
      </div>

      <section className="project-resources-section">
        <header className="project-resources-head">
          <div>
            <h2>
              项目资源
            </h2>

            <p>
              项目已经具备真实的运行边界：智能体、工具、外部服务和执行策略都会在控制层执行前完成权限过滤。
            </p>
          </div>
        </header>

        <div className="project-resource-grid">
          <button
            type="button"
            className="project-resource-card"
            onClick={() =>
              document
                .getElementById(
                  `project-knowledge-${project.id}`,
                )
                ?.scrollIntoView({
                  behavior: "smooth",
                  block: "start",
                })
            }
          >
            <div className="project-resource-icon">
              <Icon
                name="file"
                size={17}
              />
            </div>

            <div className="project-resource-copy">
              <span>
                Knowledge
              </span>

              <strong>
                {knowledgeStats.total}
                {" "}
                个文件
              </strong>

              <small>
                {knowledgeStats.ready}
                {" "}
                可检索 ·
                {" "}
                {knowledgeStats.pending}
                {" "}
                待处理
              </small>
            </div>

            <span className="project-resource-state">
              管理
            </span>
          </button>

          <button
            type="button"
            className="project-resource-card"
            onClick={() =>
              document
                .getElementById(
                  `project-runtime-${project.id}`,
                )
                ?.scrollIntoView({
                  behavior: "smooth",
                  block: "start",
                })
            }
          >
            <div className="project-resource-icon">
              <Icon
                name="agents"
                size={17}
              />
            </div>

            <div className="project-resource-copy">
              <span>
                Agents
              </span>

              <strong>
                {runtimeSummary.agentCount}
                {" / "}
                {agents.length}
                {" "}
                个可用
              </strong>

              <small>
                {runtimeSummary.agentMode === "all"
                  ? "使用全部账户级智能体"
                  : "仅使用项目已选择智能体"}
              </small>
            </div>

            <span className="project-resource-state">
              管理
            </span>
          </button>

          <button
            type="button"
            className="project-resource-card"
            onClick={() =>
              document
                .getElementById(
                  `project-runtime-${project.id}`,
                )
                ?.scrollIntoView({
                  behavior: "smooth",
                  block: "start",
                })
            }
          >
            <div className="project-resource-icon">
              <Icon
                name="extensions"
                size={17}
              />
            </div>

            <div className="project-resource-copy">
              <span>
                工具与外部服务
              </span>

              <strong>
                {runtimeSummary.toolCount}
                {" "}
                Tools ·
                {" "}
                {runtimeSummary.mcpCount}
                {" "}
                MCP
              </strong>

              <small>
                {pluginCount}
                {" "}
                个平台能力 · 项目运行环境受绑定约束
              </small>
            </div>

            <span className="project-resource-state">
              查看
            </span>
          </button>

          <button
            type="button"
            className="project-resource-card"
            onClick={() =>
              document
                .getElementById(
                  `project-runtime-${project.id}`,
                )
                ?.scrollIntoView({
                  behavior: "smooth",
                  block: "start",
                })
            }
          >
            <div className="project-resource-icon">
              <Icon
                name="sparkles"
                size={17}
              />
            </div>

            <div className="project-resource-copy">
              <span>
                Runtime Policy
              </span>

              <strong>
                {runtimeSummary.policyMode === "project"
                  ? runtimeSummary.scheduler
                  : "跟随会话"}
              </strong>

              <small>
                {runtimeSummary.policyMode === "project"
                  ? `${runtimeSummary.planner.replace("_", "-")} · ${runtimeSummary.executionMode}`
                  : "Composer Runtime Settings"}
              </small>
            </div>

            <span className="project-resource-state">
              调整
            </span>
          </button>
        </div>
      </section>

      <ProjectRuntimePanel
        projectId={project.id}
        agents={agents}
        tools={tools}
        mcpServers={mcpServers}
        onSummaryChange={
          setRuntimeSummary
        }
      />

      <ProjectKnowledge
        projectId={project.id}
        onStatsChange={
          setKnowledgeStats
        }
      />

      <ProjectGlobalKnowledgeBindings
        projectId={project.id}
      />

      {editing && (
        <div
          className="workspace-dialog-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (
              event.target ===
                event.currentTarget &&
              !editBusy
            ) {
              setEditing(
                false,
              );
            }
          }}
        >
          <form
            className="workspace-management-dialog"
            onSubmit={(event) => {
              event.preventDefault();

              void saveEdit();
            }}
          >
            <h2>
              编辑项目
            </h2>

            <label className="field">
              <span>
                项目名称
              </span>

              <input
                autoFocus
                value={editName}
                maxLength={80}
                disabled={editBusy}
                onChange={(event) =>
                  setEditName(
                    event.target.value,
                  )
                }
              />
            </label>

            <label className="field">
              <span>
                描述（可选）
              </span>

              <textarea
                value={
                  editDescription
                }
                maxLength={240}
                rows={3}
                disabled={editBusy}
                onChange={(event) =>
                  setEditDescription(
                    event.target.value,
                  )
                }
              />
            </label>

            {editError && (
              <div
                className="session-feedback"
                role="alert"
              >
                {editError}
              </div>
            )}

            <div className="workspace-management-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={editBusy}
                onClick={() =>
                  setEditing(
                    false,
                  )
                }
              >
                取消
              </button>

              <button
                type="submit"
                className="primary-button"
                disabled={
                  editBusy ||
                  !editName.trim()
                }
              >
                {editBusy
                  ? "保存中..."
                  : "保存"}
              </button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}
