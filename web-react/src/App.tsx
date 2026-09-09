import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  listAgents,
  listConversations,
  listMCPServers,
  listMessages,
  listPlugins,
  listProjects,
  listTasks,
  listTools,
  seedDesktopTools,
  deleteTask,
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
import {
  AppErrorBoundary,
  PanelLoading,
} from "./components/common/AppErrorBoundary";

import "./styles/index.css";
import "./styles/ui-v3.css";
import "./styles/theme-v4.css";
import "./styles/theme-v4-1.css";
import "./styles/theme-v4-2-soft-light.css";
import "./styles/theme-v4-4-clean-light.css";
import "./styles/theme-v4-5-user-byok.css";
import "./styles/theme-v4-6-chinese-light.css";

const Agents = lazy(() =>
  import("./features/agents/Agents").then((module) => ({
    default: module.Agents,
  })),
);

const Extensions = lazy(() =>
  import("./features/extensions/Extensions").then((module) => ({
    default: module.Extensions,
  })),
);

const Tasks = lazy(() =>
  import("./features/tasks/Tasks").then((module) => ({
    default: module.Tasks,
  })),
);

const KnowledgeCenter = lazy(() =>
  import("./features/knowledge/KnowledgeCenter").then((module) => ({
    default: module.KnowledgeCenter,
  })),
);

const Governance = lazy(() =>
  import("./features/governance/Governance").then((module) => ({
    default: module.Governance,
  })),
);

const ModelSettings = lazy(() =>
  import("./features/model-settings/ModelSettings").then((module) => ({
    default: module.ModelSettings,
  })),
);

const Ecosystem = lazy(() =>
  import("./features/ecosystem/Ecosystem").then((module) => ({
    default: module.Ecosystem,
  })),
);

const Profile = lazy(() =>
  import("./features/profile/Profile").then((module) => ({
    default: module.Profile,
  })),
);

type Tab =
  | "workspace"
  | "agents"
  | "knowledge"
  | "extensions"
  | "tasks"
  | "model-settings"
  | "governance"
  | "ecosystem"
  | "profile";

const VALID_TABS: readonly Tab[] = [
  "workspace",
  "agents",
  "knowledge",
  "extensions",
  "tasks",
  "model-settings",
  "governance",
  "ecosystem",
  "profile",
];

function isTab(value: string | null): value is Tab {
  return value != null && VALID_TABS.includes(value as Tab);
}

/**
 * 从 URL 中恢复当前一级页面。
 *
 * 示例：
 * /                         -> 工作台
 * /?page=agents             -> 智能体
 * /?page=knowledge          -> 知识库
 * /?page=ecosystem          -> 生态中心
 *
 * workspace 是默认页面，所以 URL 中不需要显式写 page=workspace。
 */
function readTabFromLocation(): Tab {
  const params = new URLSearchParams(window.location.search);
  const page = params.get("page");

  return isTab(page) ? page : "workspace";
}

/**
 * 更新当前页面对应的 URL。
 *
 * 不引入 React Router，继续保持当前项目的轻量架构。
 * 使用 History API 的好处：
 * 1. F5 可以恢复当前页面
 * 2. 浏览器前进/后退可以正常切换页面
 * 3. 不需要后端增加 SPA 路由配置
 */
function writeTabToLocation(
  tab: Tab,
  options?: {
    replace?: boolean;
  },
) {
  const url = new URL(window.location.href);

  if (tab === "workspace") {
    url.searchParams.delete("page");
  } else {
    url.searchParams.set("page", tab);
  }

  /**
   * section 是生态中心内部 Tab 使用的参数。
   *
   * 离开生态中心时删除它，避免出现：
   *
   * ?page=agents&section=api
   */
  if (tab !== "ecosystem") {
    url.searchParams.delete("section");
  }

  const nextUrl = `${url.pathname}${url.search}${url.hash}`;

  if (options?.replace) {
    window.history.replaceState(
      { page: tab },
      "",
      nextUrl,
    );
    return;
  }

  window.history.pushState(
    { page: tab },
    "",
    nextUrl,
  );
}

export default function App() {
  const [user, setUser] =
    useState<User | null>(
      null,
    );

  const [
    sessionReady,
    setSessionReady,
  ] = useState(false);

  const [
    bootError,
    setBootError,
  ] = useState("");

  const [
    shellError,
    setShellError,
  ] = useState("");

  const [
    sessionAttempt,
    setSessionAttempt,
  ] = useState(0);

  /**
   * 以前固定写：
   *
   * useState<Tab>("workspace")
   *
   * 因此每次 F5 都会回到工作台。
   *
   * 现在从 URL 初始化。
   */
  const [tab, setTab] =
    useState<Tab>(() =>
      readTabFromLocation(),
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
    messageProjection,
    setMessageProjection,
  ] =
    useState<{
      conversationId: number | null;
      items: Message[];
    }>({
      conversationId: null,
      items: [],
    });

  const [
    messageLoadFailure,
    setMessageLoadFailure,
  ] = useState<{
    conversationId: number;
    message: string;
  } | null>(null);

  // Conversation list loading is also projection-only. A late list request
  // must never override a newer explicit conversation mutation/selection.
  const conversationLoadSequenceRef = useRef(0);

  // Conversation message loading is scoped by conversation id. The visible
  // message projection carries its owning conversation id atomically, so a
  // render can never mistake A's rows for B's rows while a switch is loading.
  // Older requests are ignored and hidden/background conversations are never
  // allowed to project their rows into the active Workspace.
  const messageLoadSequenceRef = useRef(0);
  const currentConversationIdRef = useRef<number | null>(current?.id ?? null);
  currentConversationIdRef.current = current?.id ?? null;

  const [
    agents,
    setAgents,
  ] =
    useState<Agent[]>(
      [],
    );

  const [
    plugins,
    setPlugins,
  ] =
    useState<
      PluginInfo[]
    >([]);

  const [
    tasks,
    setTasks,
  ] =
    useState<Task[]>(
      [],
    );

  const [
    tools,
    setTools,
  ] =
    useState<Tool[]>(
      [],
    );

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

  /**
   * 一级页面统一导航入口。
   *
   * 后面不要再直接 setTab("xxx")。
   * 所有正常页面跳转都通过这里，
   * 这样 React 状态和浏览器 URL 永远保持一致。
   */
  const navigateToTab = (
    nextTab: Tab,
  ) => {
    setShellError("");

    if (nextTab === tab) {
      return;
    }

    writeTabToLocation(
      nextTab,
    );

    setTab(nextTab);
  };

  /**
   * 支持浏览器：
   *
   * ← 后退
   * → 前进
   *
   * History API 改变后，浏览器触发 popstate，
   * 我们重新从 URL 恢复当前页面。
   */
  useEffect(() => {
    const handlePopState =
      () => {
        setTab(
          readTabFromLocation(),
        );
      };

    window.addEventListener(
      "popstate",
      handlePopState,
    );

    return () => {
      window.removeEventListener(
        "popstate",
        handlePopState,
      );
    };
  }, []);

  /**
   * 如果有人手动输入非法页面，例如：
   *
   * ?page=abcdef
   *
   * 页面会安全回到工作台，
   * 同时把非法参数从 URL 中清理掉。
   */
  useEffect(() => {
    const params =
      new URLSearchParams(
        window.location.search,
      );

    const page =
      params.get("page");

    if (
      page != null &&
      !isTab(page)
    ) {
      writeTabToLocation(
        "workspace",
        {
          replace: true,
        },
      );

      setTab(
        "workspace",
      );
    }
  }, []);

  const loadConversations =
    async () => {
      const sequence =
        ++conversationLoadSequenceRef.current;

      const result =
        await listConversations();

      // Ignore an older projection that completed after a newer refresh was
      // already started. This is critical after create/select mutations: an
      // older list snapshot must not write A back over an authoritative B.
      if (
        sequence !==
        conversationLoadSequenceRef.current
      ) {
        return;
      }

      setConversations(
        result,
      );

      setCurrent(
        (previous) => {
          if (!previous) {
            return (
              result[0] ??
              null
            );
          }

          const refreshed =
            result.find(
              (item) =>
                item.id ===
                previous.id,
            );

          // Explicit user selection / successful mutation is authoritative.
          // If a projection is temporarily stale and does not contain the
          // selected conversation yet, preserve the selected conversation
          // instead of falling back to result[0] and jumping to another row.
          return (
            refreshed ??
            previous
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
        currentConversationIdRef.current ??
        undefined;

      if (!id) {
        ++messageLoadSequenceRef.current;
        setMessageProjection({
          conversationId: null,
          items: [],
        });
        setMessageLoadFailure(null);
        return;
      }

      // A background conversation may finish work after the user navigated
      // elsewhere. Fetching its history is unnecessary for the visible
      // projection; the normal conversation-switch effect will load it when
      // that conversation becomes active again. More importantly, do not let
      // a hidden refresh invalidate or replace the active conversation load.
      if (
        currentConversationIdRef.current !== id
      ) {
        return;
      }

      const sequence =
        ++messageLoadSequenceRef.current;

      setMessageLoadFailure(
        (failure) =>
          failure?.conversationId === id
            ? null
            : failure,
      );

      try {
        const loaded =
          await listMessages(
            id,
          );

        if (
          sequence !== messageLoadSequenceRef.current ||
          currentConversationIdRef.current !== id
        ) {
          return;
        }

        setMessageProjection({
          conversationId: id,
          items: loaded,
        });
        setMessageLoadFailure(null);
      } catch (error) {
        if (
          sequence === messageLoadSequenceRef.current &&
          currentConversationIdRef.current === id
        ) {
          setMessageLoadFailure({
            conversationId: id,
            message: friendlyApiError(
              error,
              "会话记录加载失败，请稍后重试。",
            ),
          });
        }

        throw error;
      }
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
                ? next[0] ??
                  null
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
      projectId:
        | number
        | null,
    ) => {
      if (
        projectId ==
        null
      ) {
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
        (
          currentTasks,
        ) =>
          currentTasks.filter(
            (task) =>
              task.id !==
              taskId,
          ),
      );

      setLatestRunState(
        (currentRun) =>
          currentRun
            ?.result.task.id ===
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
        (
          currentTasks,
        ) =>
          currentTasks.map(
            (task) =>
              task.id ===
              taskId
                ? updated
                : task,
          ),
      );

      setLatestRunState(
        (currentRun) =>
          currentRun
            ?.result.task.id ===
          taskId
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

  const bootstrapTools =
    async () => {
      // Desktop Agent is a built-in AgentMesh capability. Provision/repair the
      // official local.* contract once when the authenticated shell starts,
      // instead of requiring the user to click “接入本机”. SeedDesktop is
      // idempotent and preserves each tool's enabled/disabled choice.
      await seedDesktopTools();
      await loadTools();
    };

  const loadMCPServers =
    async () => {
      setMCPServers(
        await listMCPServers(),
      );
    };

  useEffect(
    () => {
      setSessionReady(
        false,
      );

      setBootError(
        "",
      );

      me()
        .then(
          setUser,
        )
        .catch(
          (error) => {
            if (
              error instanceof
                ApiError &&
              error.status ===
                401
            ) {
              return;
            }

            setBootError(
              friendlyApiError(
                error,
                "无法恢复登录状态。",
              ),
            );
          },
        )
        .finally(() =>
          setSessionReady(
            true,
          ),
        );
    },
    [
      sessionAttempt,
    ],
  );

  useEffect(
    () => {
      if (!user) {
        return;
      }

      setShellError(
        "",
      );

      Promise.all([
        loadConversations(),
        loadProjects(),
        loadAgents(),
        loadPlugins(),
        loadTasks(),
        bootstrapTools(),
        loadMCPServers(),
      ]).catch(
        (error) => {
          console.error(
            error,
          );

          setShellError(
            friendlyApiError(
              error,
              "工作台资源加载失败，请重试。",
            ),
          );
        },
      );
    },
    [
      user,
    ],
  );

  useEffect(
    () => {
      loadMessages(
        current?.id,
      ).catch(
        console.error,
      );
    },
    [
      current?.id,
    ],
  );

  const visibleMessages =
    current != null &&
    messageProjection.conversationId === current.id
      ? messageProjection.items
      : [];

  const messagesLoadError =
    current != null &&
    messageProjection.conversationId !== current.id &&
    messageLoadFailure?.conversationId === current.id
      ? messageLoadFailure.message
      : "";

  // A current conversation whose authoritative message projection has not
  // arrived yet is loading synchronously from the very first render after a
  // switch. This prevents both cross-conversation row leakage and the false
  // "empty conversation" flash that used to appear during async refetch.
  const messagesLoading =
    current != null &&
    messageProjection.conversationId !== current.id &&
    messagesLoadError === "";

  if (
    !sessionReady
  ) {
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

  if (
    bootError &&
    !user
  ) {
    return (
      <div className="session-restore-page">
        <div className="session-restore-card">
          <span className="session-restore-logo">
            AM
          </span>

          <div>
            <strong>
              暂时无法连接 AgentMesh
            </strong>

            <small>
              {
                bootError
              }
            </small>

            <button
              className="session-restore-retry"
              type="button"
              onClick={() =>
                setSessionAttempt(
                  (value) =>
                    value +
                    1,
                )
              }
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
        onDone={(
          nextUser,
        ) => {
          setUser(
            nextUser,
          );

          setBootError(
            "",
          );
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
      id: "ecosystem",
      label: "生态中心",
      icon: "sparkles",
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
    <div
      className={`app-shell app-shell-v3 tab-${tab}`}
    >
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
                    navigateToTab(
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
            <button
              type="button"
              className="user-profile-entry"
              data-testid="nav-profile"
              onClick={() => navigateToTab("profile")}
            >
              <span className="user-avatar">
                {user.displayName
                  .slice(
                    0,
                    2,
                  )
                  .toUpperCase()}
              </span>

              <span className="user-profile-copy">
                <strong>{user.displayName}</strong>
                <small>{user.email}</small>
              </span>
            </button>

            <button
              className="icon-button"
              title="退出登录"
              data-testid="auth-logout"
              onClick={async () => {
                await logout();
                setUser(null);
              }}
            >
              <Icon name="logout" size={17} />
            </button>
          </div>
        </div>
      </aside>

      <main className="app-main">
        {shellError && (
          <div
            className="shell-notice"
            role="alert"
          >
            <span>
              {
                shellError
              }
            </span>

            <button
              type="button"
              onClick={() =>
                setSessionAttempt(
                  (value) =>
                    value +
                    1,
                )
              }
            >
              重新加载
            </button>
          </div>
        )}

        <AppErrorBoundary
          resetKey={
            tab
          }
        >
          <Suspense
            fallback={
              <PanelLoading label="正在加载功能模块…" />
            }
          >
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
                  visibleMessages
                }
                messagesLoading={
                  messagesLoading
                }
                messagesLoadError={
                  messagesLoadError
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
              "ecosystem" && (
              <Ecosystem
                projects={
                  projects
                }
              />
            )}

            {tab ===
              "governance" && (
              <Governance
                projects={
                  projects
                }
              />
            )}

            {tab === "profile" && (
              <Profile
                user={user}
                projects={projects}
                conversations={conversations}
                agents={agents}
                tasks={tasks}
                onNavigate={(page) => navigateToTab(page)}
              />
            )}

            {tab ===
              "tasks" && (
              <Tasks
                tasks={
                  tasks
                }
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
