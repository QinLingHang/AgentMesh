import { lazy, Suspense, useEffect, useState } from "react";
import {
  listAgents,
  listConversations,
  listMCPServers,
  listMessages,
  listPlugins,
  listProjects,
  listTasks,
  listTools,
  deleteTask,
  createConversation,
  cancelTask,
  createProject,
  updateProject,
  deleteProject,
  renameConversation,
  deleteConversation,
  moveConversationToProject,
  removeConversationFromProject,
  logout,
  me,
  ApiError,
  friendlyApiError,
} from "./api";
import type {
  Agent,
  Conversation,
  MCPServer,
  Message,
  PluginInfo,
  Project,
  Task,
  Tool,
  User,
} from "./types";
import { Icon } from "./components/common/Icon";
import type { IconName } from "./components/common/Icon";
import { Auth } from "./features/auth/Auth";
import { Workspace } from "./features/workspace/Workspace";
import type { LatestRunState } from "./features/workspace/Workspace";
import { AppErrorBoundary, PanelLoading } from "./components/common/AppErrorBoundary";
import "./styles/index.css";
import "./styles/ui-v3.css";
import "./styles/theme-v4.css";
import "./styles/theme-v4-1.css";
import "./styles/theme-v4-2-soft-light.css";
import "./styles/theme-v4-4-clean-light.css";
import "./styles/theme-v4-5-user-byok.css";
import "./styles/theme-v4-6-chinese-light.css";

const Agents = lazy(() =>
  import("./features/agents/Agents").then((module) => ({ default: module.Agents })),
);
const Extensions = lazy(() =>
  import("./features/extensions/Extensions").then((module) => ({ default: module.Extensions })),
);
const Tasks = lazy(() =>
  import("./features/tasks/Tasks").then((module) => ({ default: module.Tasks })),
);
const KnowledgeCenter = lazy(() =>
  import("./features/knowledge/KnowledgeCenter").then((module) => ({ default: module.KnowledgeCenter })),
);
const Governance = lazy(() =>
  import("./features/governance/Governance").then((module) => ({ default: module.Governance })),
);
const ModelSettings = lazy(() =>
  import("./features/model-settings/ModelSettings").then((module) => ({ default: module.ModelSettings })),
);

type Tab =
  | "workspace"
  | "agents"
  | "knowledge"
  | "extensions"
  | "tasks"
  | "model-settings"
  | "governance";

export default function App() {
  const [user, setUser] =
    useState<User | null>(
      null,
    );

  const [
    sessionReady,
    setSessionReady,
  ] =
    useState(false);

  const [bootError, setBootError] = useState("");
  const [shellError, setShellError] = useState("");
  const [sessionAttempt, setSessionAttempt] = useState(0);

  const [tab, setTab] =
    useState<Tab>(
      "workspace",
    );

  const [
    conversations,
    setConversations,
  ] =
    useState<
      Conversation[]
    >([]);

  const [
    current,
    setCurrent,
  ] =
    useState<Conversation | null>(
      null,
    );

  const [
    projects,
    setProjects,
  ] =
    useState<Project[]>(
      [],
    );

  const [
    messages,
    setMessages,
  ] =
    useState<Message[]>(
      [],
    );

  const [agents, setAgents] =
    useState<Agent[]>([]);

  const [
    plugins,
    setPlugins,
  ] =
    useState<
      PluginInfo[]
    >([]);

  const [tasks, setTasks] =
    useState<Task[]>([]);

  const [tools, setTools] =
    useState<Tool[]>([]);

  const [
    mcpServers,
    setMCPServers,
  ] =
    useState<
      MCPServer[]
    >([]);

  const [
    latestRunState,
    setLatestRunState,
  ] =
    useState<LatestRunState | null>(
      null,
    );

  const loadConversations =
    async () => {
      const result =
        await listConversations();

      setConversations(
        result,
      );

      setCurrent(
        (previous) => {
          if (previous) {
            const refreshed =
              result.find(
                (item) =>
                  item.id ===
                  previous.id,
              );

            if (refreshed) {
              return refreshed;
            }
          }

          return (
            result[0] ??
            null
          );
        },
      );
    };

  const loadProjects =
    async () => {
      setProjects(
        await listProjects(),
      );
    };

  const loadMessages =
    async (
      conversationId?: number,
    ) => {
      const id =
        conversationId ??
        current?.id;

      if (!id) {
        setMessages([]);
        return;
      }

      setMessages(
        await listMessages(
          id,
        ),
      );
    };

  const handleRenameConversation =
    async (
      conversationId: number,
      title: string,
    ) => {
      const updated =
        await renameConversation(
          conversationId,
          title,
        );

      setConversations(
        (items) =>
          items.map(
            (item) =>
              item.id ===
              updated.id
                ? updated
                : item,
          ),
      );

      setCurrent(
        (item) =>
          item?.id ===
          updated.id
            ? updated
            : item,
      );

      return updated;
    };

  const handleDeleteConversation =
    async (
      conversationId: number,
    ) => {
      await deleteConversation(
        conversationId,
      );

      setConversations(
        (items) => {
          const next =
            items.filter(
              (item) =>
                item.id !==
                conversationId,
            );

          setCurrent(
            (active) =>
              active?.id ===
              conversationId
                ? next[0] ?? null
                : active,
          );

          return next;
        },
      );

      setLatestRunState(
        (run) =>
          run?.conversationId ===
          conversationId
            ? null
            : run,
      );

      await loadProjects();
    };

  const handleStartNewTask = async () => {
    try {
      setShellError("");
      setTab("workspace");
      const conversation = await createConversation("新会话");
      setConversations((items) => [conversation, ...items.filter((item) => item.id !== conversation.id)]);
      setCurrent(conversation);
      setMessages([]);
      setLatestRunState(null);
      await Promise.allSettled([loadConversations(), loadProjects()]);
    } catch (error) {
      setShellError(friendlyApiError(error, "创建新任务失败，请稍后重试。"));
    }
  };

  const handleOpenPersonalWorkspace = () => {
    setShellError("");
    setTab("workspace");
  };

  const handleCreateProject =
    async (
      name: string,
      description: string,
    ) => {
      const created =
        await createProject(
          name,
          description,
        );

      setProjects(
        (items) => [
          created,
          ...items,
        ],
      );

      return created;
    };

  const handleUpdateProject =
    async (
      projectId: number,
      name: string,
      description: string,
    ) => {
      const updated =
        await updateProject(
          projectId,
          name,
          description,
        );

      setProjects(
        (items) =>
          items.map(
            (item) =>
              item.id ===
              updated.id
                ? updated
                : item,
          ),
      );

      return updated;
    };

  const handleDeleteProject =
    async (
      projectId: number,
    ) => {
      await deleteProject(
        projectId,
      );

      setProjects(
        (items) =>
          items.filter(
            (item) =>
              item.id !==
              projectId,
          ),
      );
    };

  const handleMoveConversation =
    async (
      conversationId: number,
      projectId: number | null,
    ) => {
      if (projectId == null) {
        await removeConversationFromProject(
          conversationId,
        );
      } else {
        await moveConversationToProject(
          conversationId,
          projectId,
        );
      }

      await loadProjects();
    };

  const loadAgents =
    async () => {
      setAgents(
        await listAgents(),
      );
    };

  const loadPlugins =
    async () => {
      setPlugins(
        await listPlugins(),
      );
    };

  const loadTasks =
    async () => {
      setTasks(
        await listTasks(),
      );
    };

  const handleDeleteTask =
    async (
      taskId: number,
    ) => {
      await deleteTask(
        taskId,
      );

      setTasks(
        (currentTasks) =>
          currentTasks.filter(
            (task) =>
              task.id !==
              taskId,
          ),
      );

      setLatestRunState(
        (currentRun) =>
          currentRun?.result
            .task.id ===
          taskId
            ? null
            : currentRun,
      );
    };

  const handleCancelTask =
    async (
      taskId: number,
    ) => {
      const updated =
        await cancelTask(
          taskId,
        );

      setTasks(
        (currentTasks) =>
          currentTasks.map(
            (task) =>
              task.id === taskId
                ? updated
                : task,
          ),
      );

      setLatestRunState(
        (currentRun) =>
          currentRun?.result.task.id === taskId
            ? null
            : currentRun,
      );
    };

  const loadTools =
    async () => {
      setTools(
        await listTools(),
      );
    };

  const loadMCPServers =
    async () => {
      setMCPServers(
        await listMCPServers(),
      );
    };

  useEffect(
    () => {
      setSessionReady(false);
      setBootError("");

      me()
        .then(setUser)
        .catch((error) => {
          if (error instanceof ApiError && error.status === 401) {
            return;
          }

          setBootError(
            friendlyApiError(error, "无法恢复登录状态。"),
          );
        })
        .finally(() => setSessionReady(true));
    },
    [sessionAttempt],
  );

  useEffect(
    () => {
      if (!user) {
        return;
      }

      setShellError("");

      Promise.all([
        loadConversations(),
        loadProjects(),
        loadAgents(),
        loadPlugins(),
        loadTasks(),
        loadTools(),
        loadMCPServers(),
      ]).catch((error) => {
        console.error(error);
        setShellError(
          friendlyApiError(error, "工作台资源加载失败，请重试。"),
        );
      });
    },
    [user],
  );

  useEffect(
    () => {
      loadMessages(
        current?.id,
      ).catch(
        console.error,
      );
    },
    [current?.id],
  );

  if (!sessionReady) {
    return (
      <div className="session-restore-page">
        <div className="session-restore-card">
          <span className="session-restore-logo">
            AM
          </span>

          <div>
            <strong>
              AgentMesh
            </strong>

            <small>
              正在恢复登录状态...
            </small>
          </div>
        </div>
      </div>
    );
  }

  if (bootError && !user) {
    return (
      <div className="session-restore-page">
        <div className="session-restore-card">
          <span className="session-restore-logo">AM</span>
          <div>
            <strong>暂时无法连接 AgentMesh</strong>
            <small>{bootError}</small>
            <button
              className="session-restore-retry"
              type="button"
              onClick={() => setSessionAttempt((value) => value + 1)}
            >
              重新连接
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <Auth
        onDone={(nextUser) => {
          setUser(nextUser);
          setBootError("");
        }}
      />
    );
  }

  const navItems: {
    id: Tab;
    label: string;
    icon: IconName;
  }[] = [
    {
      id: "workspace",
      label: "工作台",
      icon: "workspace",
    },
    {
      id: "agents",
      label: "智能体",
      icon: "agents",
    },
    {
      id: "knowledge",
      label: "知识库",
      icon: "file",
    },
    {
      id: "extensions",
      label: "能力中心",
      icon: "extensions",
    },
    {
      id: "tasks",
      label: "任务记录",
      icon: "tasks",
    },
    {
      id: "model-settings",
      label: "模型设置",
      icon: "server",
    },
    {
      id: "governance",
      label: "治理与安全",
      icon: "shield",
    },
  ];

  return (
    <div className={`app-shell app-shell-v3 tab-${tab}`}>
      <aside className="global-sidebar">
        <div>
          <div className="brand">
            <span className="brand-mark">
              AM
            </span>

            <div>
              <strong>
                AgentMesh
              </strong>

              <small>
                让 AI 团队为你工作
              </small>
            </div>
          </div>

          <button
            type="button"
            className="workspace-switcher"
            onClick={handleOpenPersonalWorkspace}
          >
            <span className="workspace-switcher-mark">P</span>
            <span>
              <strong>个人工作空间</strong>
              <small>个人任务与项目工作台</small>
            </span>
            <Icon name="chevron" size={14} />
          </button>

          <button
            type="button"
            className="sidebar-primary-action"
            onClick={() => void handleStartNewTask()}
          >
            <Icon name="plus" size={17} />
            开始新任务
          </button>

          <nav className="global-nav">
            {navItems.map(
              (item) => (
                <button
                  className={
                    tab ===
                    item.id
                      ? "active"
                      : ""
                  }
                  key={
                    item.id
                  }
                  data-testid={`nav-${item.id}`}
                  onClick={() =>
                    setTab(
                      item.id,
                    )
                  }
                >
                  <Icon
                    name={
                      item.icon
                    }
                    size={18}
                  />

                  <span>
                    {
                      item.label
                    }
                  </span>
                </button>
              ),
            )}
          </nav>
        </div>

        <div className="sidebar-footer">
          <div className="user-card">
            <span className="user-avatar">
              {user.displayName
                .slice(
                  0,
                  2,
                )
                .toUpperCase()}
            </span>

            <div>
              <strong>
                {
                  user.displayName
                }
              </strong>

              <small>
                {
                  user.email
                }
              </small>
            </div>

            <button
              className="icon-button"
              title="退出登录"
              data-testid="auth-logout"
              onClick={async () => {
                await logout();

                setUser(
                  null,
                );
              }}
            >
              <Icon
                name="logout"
                size={17}
              />
            </button>
          </div>
        </div>
      </aside>

      <main className="app-main">
        {shellError && (
          <div className="shell-notice" role="alert">
            <span>{shellError}</span>
            <button type="button" onClick={() => setSessionAttempt((value) => value + 1)}>重新加载</button>
          </div>
        )}

        <AppErrorBoundary resetKey={tab}>
          <Suspense fallback={<PanelLoading label="正在加载功能模块…" />}>
        {tab ===
          "workspace" && (
          <Workspace
            conversations={
              conversations
            }
            projects={
              projects
            }
            current={
              current
            }
            setCurrent={
              setCurrent
            }
            messages={
              messages
            }
            tasks={
              tasks
            }
            latestRunState={
              latestRunState
            }
            setLatestRunState={
              setLatestRunState
            }
            reloadConversations={
              loadConversations
            }
            reloadProjects={
              loadProjects
            }
            renameConversation={
              handleRenameConversation
            }
            deleteConversation={
              handleDeleteConversation
            }
            createProject={
              handleCreateProject
            }
            updateProject={
              handleUpdateProject
            }
            deleteProject={
              handleDeleteProject
            }
            moveConversation={
              handleMoveConversation
            }
            reloadMessages={
              loadMessages
            }
            reloadTasks={
              loadTasks
            }
            agents={
              agents
            }
            pluginCount={
              plugins.length
            }
            tools={
              tools
            }
            mcpServers={
              mcpServers
            }
          />
        )}

        {tab ===
          "agents" && (
          <Agents
            agents={
              agents
            }
            reload={
              loadAgents
            }
          />
        )}

        {tab ===
          "knowledge" && (
          <KnowledgeCenter
            projects={
              projects
            }
            onCreateProject={
              handleCreateProject
            }
          />
        )}

        {tab ===
          "extensions" && (
          <Extensions
            plugins={
              plugins
            }
            tools={
              tools
            }
            mcpServers={
              mcpServers
            }
            reloadTools={
              loadTools
            }
            reloadMCP={
              loadMCPServers
            }
          />
        )}

        {tab ===
          "model-settings" && (
          <ModelSettings />
        )}

        {tab ===
          "governance" && (
          <Governance projects={projects} />
        )}

        {tab ===
          "tasks" && (
          <Tasks
            tasks={tasks}
            onDeleteTask={
              handleDeleteTask
            }
            onCancelTask={
              handleCancelTask
            }
          />
        )}
          </Suspense>
        </AppErrorBoundary>
      </main>
    </div>
  );
}
