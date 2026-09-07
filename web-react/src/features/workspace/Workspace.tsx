import { lazy, Suspense, useEffect, useState } from "react";
import {
  createConversation,
  decideTaskApproval,
  deleteConversation,
  deleteConversationAttachment,
  friendlyApiError,
  resumeTask,
  runTask,
  runTaskStream,
  uploadConversationAttachment,
} from "../../api";
import type {
  Agent,
  Conversation,
  DeliveryMode,
  ExecutionMode,
  MCPServer,
  Message,
  MessageAttachmentMetadata,
  Planner,
  Project,
  RunResult,
  Scheduler,
  SynthesisMode,
  Task,
  Tool,
} from "../../types";
import { Icon } from "../../components/common/Icon";
import {
  isWaitingStatus,
  RuntimeStatusBadge,
} from "../../components/common/RuntimeStatusBadge";
import { SessionRail } from "./SessionRail";
import { MessageHistory } from "./MessageHistory";
import { ResumePanel } from "./ResumePanel";
import { RunSettingsDrawer } from "./RunSettingsDrawer";
import { ProjectHome } from "./ProjectHome";
import { AttachmentStrip, type ComposerAttachment } from "./AttachmentStrip";

const RunDetails = lazy(() =>
  import("../run-details/RunDetails").then((module) => ({ default: module.RunDetails })),
);

const UNTITLED_TITLES =
  new Set([
    "新任务",
    "新会话",
    "新对话",
    "AgentMesh 新任务",
  ]);

function deriveConversationTitle(
  task: string,
) {
  const normalized =
    task
      .replace(
        /\s+/g,
        " ",
      )
      .trim();

  const chars =
    Array.from(
      normalized,
    );

  if (
    chars.length <= 28
  ) {
    return normalized ||
      "新会话";
  }

  return `${chars
    .slice(
      0,
      28,
    )
    .join("")}…`;
}

export type LatestRunState = {
  conversationId: number;
  result: RunResult;
};

export function Workspace({
  conversations,
  projects,
  current,
  setCurrent,
  messages,
  tasks,
  latestRunState,
  setLatestRunState,
  reloadConversations,
  reloadProjects,
  renameConversation,
  deleteConversation,
  createProject,
  updateProject,
  deleteProject,
  moveConversation,
  reloadMessages,
  reloadTasks,
  agents,
  pluginCount,
  tools,
  mcpServers,
}: {
  conversations: Conversation[];
  projects: Project[];
  current: Conversation | null;
  setCurrent: (
    conversation: Conversation,
  ) => void;
  messages: Message[];
  tasks: Task[];
  latestRunState: LatestRunState | null;
  setLatestRunState: (
    value: LatestRunState | null,
  ) => void;
  reloadConversations: () => Promise<void>;
  reloadProjects: () => Promise<void>;
  renameConversation: (
    conversationId: number,
    title: string,
  ) => Promise<Conversation>;
  deleteConversation: (
    conversationId: number,
  ) => Promise<void>;
  createProject: (
    name: string,
    description: string,
  ) => Promise<Project>;
  updateProject: (
    projectId: number,
    name: string,
    description: string,
  ) => Promise<Project>;
  deleteProject: (
    projectId: number,
  ) => Promise<void>;
  moveConversation: (
    conversationId: number,
    projectId: number | null,
  ) => Promise<void>;
  reloadMessages: (
    conversationId?: number,
  ) => Promise<void>;
  reloadTasks: () => Promise<void>;
  agents: Agent[];
  pluginCount: number;
  tools: Tool[];
  mcpServers: MCPServer[];
}) {
  const [text, setText] = useState("");

  const [scheduler, setScheduler] =
    useState<Scheduler>(
      "adaptive",
    );

  const [planner, setPlanner] =
    useState<Planner>(
      "multi_objective",
    );

  const [executionMode, setExecutionMode] =
    useState<ExecutionMode>(
      "auto",
    );

  const [synthesisMode, setSynthesisMode] =
    useState<SynthesisMode>(
      "auto",
    );

  const [deliveryMode, setDeliveryMode] =
    useState<DeliveryMode>(
      "direct",
    );

  const [latency, setLatency] =
    useState(8000);

  const [cost, setCost] =
    useState(0.15);

  const [quality, setQuality] =
    useState(0.8);

  const [retryOnWorkerLoss, setRetryOnWorkerLoss] =
    useState(false);

  const [busy, setBusy] =
    useState(false);

  const [pendingPrompt, setPendingPrompt] =
    useState("");

  const [pendingAttachments, setPendingAttachments] =
    useState<MessageAttachmentMetadata[]>([]);

  const [streamingAnswer, setStreamingAnswer] =
    useState("");

  const [streamingPhase, setStreamingPhase] =
    useState("");

  const [error, setError] =
    useState("");

  const [attachments, setAttachments] =
    useState<ComposerAttachment[]>([]);

  const [resumeText, setResumeText] =
    useState("");

  const [resumeBusy, setResumeBusy] =
    useState(false);

  const [resumeError, setResumeError] =
    useState("");

  const [showDetails, setShowDetails] =
    useState(false);

  const [detailsResult, setDetailsResult] =
    useState<RunResult | null>(
      null,
    );

  const [showSettings, setShowSettings] =
    useState(false);

  const [railCollapsed, setRailCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem("agentmesh.workspace.railCollapsed") === "1";
    } catch {
      return false;
    }
  });

  const toggleRail = () => {
    setRailCollapsed((value) => {
      const next = !value;
      try {
        window.localStorage.setItem("agentmesh.workspace.railCollapsed", next ? "1" : "0");
      } catch {
        // Local preference persistence is best-effort only.
      }
      return next;
    });
  };

  const [
    selectedProjectId,
    setSelectedProjectId,
  ] =
    useState<number | null>(
      null,
    );

  const selectedProject =
    selectedProjectId == null
      ? null
      : projects.find(
          (project) =>
            project.id ===
            selectedProjectId,
        ) ?? null;

  const selectedProjectConversations =
    selectedProject
      ? selectedProject.conversationIds
          .map(
            (id) =>
              conversations.find(
                (conversation) =>
                  conversation.id ===
                  id,
              ),
          )
          .filter(
            (
              value,
            ): value is Conversation =>
              value != null,
          )
      : [];

  const latestRun =
    latestRunState &&
    latestRunState.conversationId ===
      current?.id
      ? latestRunState.result
      : null;

  // =====================================================
  // Durable Waiting Task
  // =====================================================

  const persistedWaitingTask =
    current
      ? tasks.find(
          (task) =>
            task.conversationId ===
              current.id &&
            isWaitingStatus(
              task.status,
            ),
        ) ?? null
      : null;

  const latestWaitingTask =
    latestRun &&
    isWaitingStatus(
      latestRun.status,
    )
      ? latestRun.task
      : null;

  const waitingTask =
    latestWaitingTask ??
    persistedWaitingTask;

  useEffect(
    () => {
      if (
        selectedProjectId != null &&
        !projects.some(
          (project) =>
            project.id ===
            selectedProjectId,
        )
      ) {
        setSelectedProjectId(
          null,
        );
      }
    },
    [
      projects,
      selectedProjectId,
    ],
  );

  useEffect(
    () => {
      setResumeText("");
      setResumeError("");
      setError("");
      setShowDetails(false);
      setDetailsResult(null);
      setShowSettings(false);
    },
    [current?.id],
  );

  const durablePending =
    latestRun != null &&
    latestRun.task.deliveryMode === "durable" &&
    (latestRun.status === "QUEUED" ||
      latestRun.status === "RUNNING");

  useEffect(
    () => {
      if (!durablePending || !current) {
        return;
      }

      const refresh = () => {
        void Promise.allSettled([
          reloadTasks(),
          reloadMessages(current.id),
          reloadConversations(),
        ]);
      };

      refresh();
      const timer = window.setInterval(
        refresh,
        1000,
      );

      return () =>
        window.clearInterval(timer);
    },
    [
      durablePending,
      current?.id,
      reloadTasks,
      reloadMessages,
      reloadConversations,
    ],
  );

  useEffect(
    () => {
      if (!durablePending || !latestRun) {
        return;
      }

      const persisted = tasks.find(
        (task) => task.id === latestRun.task.id,
      );

      if (
        persisted &&
        persisted.status !== "QUEUED" &&
        persisted.status !== "RUNNING"
      ) {
        // The callback has reached MySQL. From here the persisted assistant
        // message is authoritative and Historical Run reconstruction takes over.
        setLatestRunState(null);
      }
    },
    [durablePending, latestRun, tasks, setLatestRunState],
  );

  const create = async (
    projectId?: number,
  ) => {
    const conversation =
      await createConversation(
        "新会话",
      );

    try {
      if (projectId != null) {
        await moveConversation(
          conversation.id,
          projectId,
        );
      }
    } catch (error) {
      // The conversation POST succeeded but project assignment failed.
      // Roll the new conversation back so Project Home never leaves
      // silent orphan conversations in the Recent list.
      try {
        await deleteConversation(
          conversation.id,
        );
      } catch {
        // Preserve the original assignment error.
      }

      await Promise.allSettled([
        reloadConversations(),
        reloadProjects(),
      ]);

      throw error;
    }

    await Promise.all([
      reloadConversations(),
      reloadProjects(),
    ]);

    setCurrent(
      conversation,
    );

    setSelectedProjectId(
      null,
    );

    setLatestRunState(
      null,
    );
  };

  const openConversation = (
    conversation: Conversation,
  ) => {
    setSelectedProjectId(
      null,
    );

    setCurrent(
      conversation,
    );
  };

  const openProject = (
    project: Project,
  ) => {
    setSelectedProjectId(
      project.id,
    );

    setShowDetails(
      false,
    );

    setDetailsResult(
      null,
    );

    setShowSettings(
      false,
    );
  };

  const ensureAttachmentConversation = async () => {
    if (current) return current;

    const conversation = await createConversation("新会话");
    setCurrent(conversation);
    await reloadConversations();
    return conversation;
  };

  const addAttachments = async (files: File[]) => {
    const allowed = new Set(["png", "jpg", "jpeg", "webp", "pdf", "docx", "txt", "md", "markdown", "csv", "json"]);
    const existingCount = attachments.filter((item) => item.status !== "error").length;
    const selected = files.slice(0, Math.max(0, 6 - existingCount));

    if (!selected.length) {
      setError("每次任务最多添加 6 个附件。");
      return;
    }

    const valid: File[] = [];
    for (const file of selected) {
      const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (!allowed.has(extension)) {
        setError(`不支持 ${file.name}。支持图片、PDF、DOCX、TXT、Markdown、CSV 和 JSON。`);
        continue;
      }
      if (file.size <= 0 || file.size > 10 * 1024 * 1024) {
        setError(`${file.name} 超过 10 MB 限制或为空文件。`);
        continue;
      }
      valid.push(file);
    }
    if (!valid.length) return;

    try {
      setError("");
      const conversation = await ensureAttachmentConversation();

      await Promise.all(valid.map(async (file) => {
        const localId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
        const previewUrl = file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined;
        const draft: ComposerAttachment = { localId, file, progress: 0, status: "uploading", previewUrl };
        setAttachments((currentItems) => [...currentItems, draft]);

        try {
          const server = await uploadConversationAttachment(
            conversation.id,
            file,
            (progress) => setAttachments((currentItems) => currentItems.map((item) =>
              item.localId === localId ? { ...item, progress } : item
            )),
          );
          setAttachments((currentItems) => currentItems.map((item) =>
            item.localId === localId ? { ...item, progress: 100, status: "ready", server } : item
          ));
        } catch (uploadError) {
          setAttachments((currentItems) => currentItems.map((item) =>
            item.localId === localId
              ? { ...item, status: "error", error: friendlyApiError(uploadError, "上传失败") }
              : item
          ));
        }
      }));
    } catch (uploadError) {
      setError(friendlyApiError(uploadError, "无法创建会话并上传附件。"));
    }
  };

  const removeAttachment = async (localId: string) => {
    const item = attachments.find((candidate) => candidate.localId === localId);
    if (!item) return;
    setAttachments((currentItems) => currentItems.filter((candidate) => candidate.localId !== localId));
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
    if (item.server) {
      try {
        await deleteConversationAttachment(item.server.conversationId, item.server.id);
      } catch {
        // Removing from the composer is authoritative for this unsent message.
        // Server cleanup remains best-effort and ownership-scoped.
      }
    }
  };


  const run = async () => {
    const readyAttachments = attachments.filter((item) => item.status === "ready" && item.server);
    const uploading = attachments.some((item) => item.status === "uploading");
    if (uploading) {
      setError("附件仍在上传，请稍候。");
      return;
    }
    if (!text.trim() && readyAttachments.length === 0) {
      return;
    }

    if (waitingTask) {
      setError("当前会话存在等待继续的任务，请先完成该任务。");
      return;
    }

    const submittedPrompt = text.trim() || "请分析我附加的内容，并给出清晰的结论。";
    const submittedAttachments = readyAttachments.slice();
    const submittedAttachmentMetadata: MessageAttachmentMetadata[] = submittedAttachments.map((item) => ({
      id: item.server!.id,
      name: item.server!.originalName,
      mediaType: item.server!.mediaType,
      extension: item.server!.extension,
      sizeBytes: item.server!.sizeBytes,
    }));

    // Optimistic composer clear: once the user submits, the input area should
    // immediately become available visually instead of retaining stale text
    // for the entire model round-trip. We restore it on failure.
    setPendingPrompt(submittedPrompt);
    setPendingAttachments(submittedAttachmentMetadata);
    setStreamingAnswer("");
    setStreamingPhase("正在连接模型…");
    setText("");
    setAttachments([]);

    try {
      setBusy(true);
      setError("");

      let conversation = current;
      if (!conversation) {
        conversation = await createConversation("新会话");
        setCurrent(conversation);
        await reloadConversations();
      }

      const input = {
        conversationId: conversation.id,
        task: submittedPrompt,
        scheduler,
        planner,
        executionMode,
        synthesisMode,
        deliveryMode,
        maxLatencyMs: latency,
        maxCost: cost,
        minQuality: quality,
        retryOnWorkerLoss: deliveryMode === "durable" ? retryOnWorkerLoss : false,
        attachmentIds: submittedAttachments.map((item) => item.server!.id),
      };

      const result = deliveryMode === "direct"
        ? await runTaskStream(input, {
            onDelta: (delta) => {
              setStreamingPhase("正在生成回答…");
              setStreamingAnswer((currentText) => currentText + delta);
            },
            onStatus: (message) => setStreamingPhase(message),
          })
        : await runTask(input);

      setLatestRunState({ conversationId: conversation.id, result });

      if (UNTITLED_TITLES.has(conversation.title)) {
        try {
          const renamed = await renameConversation(conversation.id, deriveConversationTitle(submittedPrompt));
          conversation = renamed;
          setCurrent(renamed);
        } catch {
          // Auto-title failure must never fail the task itself.
        }
      }

      await Promise.all([
        reloadMessages(conversation.id),
        reloadTasks(),
        reloadConversations(),
      ]);

      submittedAttachments.forEach((item) => {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      });
      setPendingPrompt("");
      setPendingAttachments([]);
      setStreamingAnswer("");
      setStreamingPhase("");
    } catch (e) {
      setError(friendlyApiError(e, "任务提交失败，请稍后重试。"));
      setText((currentText) => currentText.trim() ? currentText : submittedPrompt);
      setAttachments((currentItems) => currentItems.length ? currentItems : submittedAttachments);
      setPendingPrompt("");
      setPendingAttachments([]);
      setStreamingAnswer("");
      setStreamingPhase("");
    } finally {
      setBusy(false);
    }
  };

  const resume = async () => {
    if (
      !waitingTask ||
      !current ||
      !resumeText.trim()
    ) {
      return;
    }

    try {
      setResumeBusy(true);
      setResumeError("");

      const result =
        await resumeTask(
          waitingTask.id,
          resumeText.trim(),
        );

      setLatestRunState({
        conversationId:
          current.id,
        result,
      });

      await Promise.all([
        reloadMessages(
          current.id,
        ),
        reloadTasks(),
        reloadConversations(),
      ]);

      setResumeText("");

      if (
        result.status ===
        "COMPLETED"
      ) {
        setShowDetails(false);
        setDetailsResult(null);
      }
    } catch (e) {
      setResumeError(
        friendlyApiError(e, "任务继续失败，请稍后重试。"),
      );
    } finally {
      setResumeBusy(false);
    }
  };

  const openRunDetails = (
    result: RunResult,
  ) => {
    setDetailsResult(
      result,
    );
    setShowDetails(
      true,
    );
  };

  const closeRunDetails = () => {
    setShowDetails(
      false,
    );
    setDetailsResult(
      null,
    );
  };

  const detailsOpen =
    selectedProject == null &&
    showDetails &&
    detailsResult !== null;

  const decideApproval = async (decision: "approve" | "reject") => {
    if (!waitingTask || !current) {
      return;
    }

    try {
      setResumeBusy(true);
      setResumeError("");

      const result = await decideTaskApproval(
        waitingTask.id,
        decision,
      );

      setLatestRunState({
        conversationId: current.id,
        result,
      });

      await Promise.all([
        reloadMessages(current.id),
        reloadTasks(),
        reloadConversations(),
      ]);

      if (result.status === "COMPLETED") {
        setShowDetails(false);
        setDetailsResult(null);
      }
    } catch (e) {
      setResumeError(friendlyApiError(e, "审批操作失败，请稍后重试。"));
    } finally {
      setResumeBusy(false);
    }
  };

  return (
    <div className={`workspace-layout ${railCollapsed ? "rail-collapsed" : ""}`}>
      <SessionRail
        conversations={
          conversations
        }
        projects={
          projects
        }
        current={current}
        setCurrent={
          openConversation
        }
        create={create}
        renameConversation={
          renameConversation
        }
        deleteConversation={
          deleteConversation
        }
        createProject={
          createProject
        }
        updateProject={
          updateProject
        }
        deleteProject={
          deleteProject
        }
        moveConversation={
          moveConversation
        }
        selectedProjectId={
          selectedProjectId
        }
        onOpenProject={
          openProject
        }
      />

      <div
        className={`workspace-stage ${detailsOpen ? "details-open" : ""}`}
      >
        {selectedProject ? (
          <ProjectHome
            project={
              selectedProject
            }
            conversations={
              selectedProjectConversations
            }
            tasks={tasks}
            agents={
              agents
            }
            pluginCount={
              pluginCount
            }
            tools={
              tools
            }
            mcpServers={
              mcpServers
            }
            onOpenConversation={
              openConversation
            }
            onCreateConversation={() =>
              create(
                selectedProject.id,
              )
            }
            onUpdateProject={
              updateProject
            }
          />
        ) : (
        <section className="workspace-core">
            <header className="workspace-toolbar">
            <div>
              <div className="workspace-breadcrumb">
                <span>工作台</span>
                <i>/</i>
                <strong className="workspace-title">
                  {current?.title || "新任务"}
                </strong>
              </div>

              <small>
                让 AgentMesh 负责规划、协作与执行，你只需要关注结果。
              </small>
            </div>

            <div className="workspace-toolbar-actions">
              <button
                type="button"
                className="workspace-rail-toggle"
                onClick={toggleRail}
                title={railCollapsed ? "展开任务与项目" : "进入专注模式"}
              >
                <Icon name="workspace" size={14} />
                <span>{railCollapsed ? "展开列表" : "专注模式"}</span>
              </button>
              {waitingTask && <RuntimeStatusBadge status={waitingTask.status} />}
            </div>
          </header>

          <div className="workspace-scroll">
            <div className="workspace-scroll-inner">
              <MessageHistory
                messages={messages}
                tasks={tasks}
                latestRun={latestRun}
                openDetails={openRunDetails}
                onSelectPrompt={(prompt) => {
                  setText(prompt);
                }}
                working={busy || durablePending}
                pendingPrompt={pendingPrompt}
                pendingAttachments={pendingAttachments}
                streamingAnswer={streamingAnswer}
                streamingPhase={streamingPhase}
              />
            </div>
          </div>

          <div className="workspace-composer-area">
            {waitingTask ? (
              <ResumePanel
                task={waitingTask}
                latestRun={latestRun}
                value={resumeText}
                setValue={setResumeText}
                busy={resumeBusy}
                error={resumeError}
                onResume={resume}
                onApprovalDecision={decideApproval}
                openDetails={() => {
                  if (latestRun) {
                    openRunDetails(
                      latestRun,
                    );
                  }
                }}
              />
            ) : (
              <div
                className="composer composer-compact attachment-drop-zone"
                onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
                onDrop={(event) => {
                  event.preventDefault();
                  if (!busy) void addAttachments(Array.from(event.dataTransfer.files ?? []));
                }}
                onPaste={(event) => {
                  if (busy) return;

                  const imageFiles = Array.from(event.clipboardData?.items ?? [])
                    .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
                    .map((item) => item.getAsFile())
                    .filter((file): file is File => file !== null)
                    .map((file, index) => {
                      const currentExtension = file.name.split(".").pop()?.toLowerCase() ?? "";
                      if (["png", "jpg", "jpeg", "webp"].includes(currentExtension)) return file;

                      const extension = file.type === "image/jpeg"
                        ? "jpg"
                        : file.type === "image/webp"
                          ? "webp"
                          : "png";

                      return new File(
                        [file],
                        `pasted-image-${Date.now()}-${index + 1}.${extension}`,
                        { type: file.type || `image/${extension}`, lastModified: file.lastModified || Date.now() },
                      );
                    });

                  if (imageFiles.length) {
                    event.preventDefault();
                    void addAttachments(imageFiles);
                  }
                }}
              >
                <textarea
                  value={text}
                  rows={3}
                  placeholder={busy ? "可以继续输入下一条消息…" : "描述目标，AgentMesh 会自动规划并执行..."}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                      e.preventDefault();
                      void run();
                    }
                  }}
                />

                <AttachmentStrip
                  items={attachments}
                  disabled={false}
                  onFiles={(files) => void addAttachments(files)}
                  onRemove={(localId) => void removeAttachment(localId)}
                />

                <footer className="composer-footer composer-footer-clean">
                  <button
                    className="composer-settings-button"
                    onClick={() =>
                      setShowSettings(
                        true,
                      )
                    }
                    type="button"
                  >
                    <span className="composer-settings-icon">
                      <Icon
                        name="tool"
                        size={14}
                      />
                    </span>

                    <span className="composer-settings-copy">
                      <strong>
                        执行偏好
                      </strong>

                      <small>
                        自动选择合适的执行方式
                      </small>
                    </span>
                  </button>

                  <span className="composer-keyboard-hint">
                    Ctrl / ⌘ + Enter
                  </span>

                  <button
                    className="primary-button run-button"
                    disabled={
                      busy ||
                      attachments.some((item) => item.status === "uploading") ||
                      (!text.trim() && !attachments.some((item) => item.status === "ready" && item.server))
                    }
                    onClick={() =>
                      void run()
                    }
                  >
                    {busy ? (
                      <>
                        <span className="spinner" />

                        正在运行
                      </>
                    ) : (
                      <>
                        运行任务

                        <Icon
                          name="arrow"
                          size={15}
                        />
                      </>
                    )}
                  </button>
                </footer>
              </div>
            )}

            {error && (
              <div className="error-box composer-error">
                {error}
              </div>
            )}
          </div>
        </section>
        )}

        {detailsOpen && detailsResult && (
          <div
            className="workspace-details-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                closeRunDetails();
              }
            }}
          >
            <aside className="workspace-details-drawer" role="dialog" aria-modal="true" aria-label="运行详情">
              <Suspense fallback={<div className="empty-state">正在加载 Run Details…</div>}>
                <RunDetails result={detailsResult} onBack={closeRunDetails} display="drawer" />
              </Suspense>
            </aside>
          </div>
        )}

        <RunSettingsDrawer
          open={showSettings}
          onClose={() =>
            setShowSettings(
              false,
            )
          }
          scheduler={scheduler}
          setScheduler={setScheduler}
          planner={planner}
          setPlanner={setPlanner}
          executionMode={executionMode}
          setExecutionMode={setExecutionMode}
          synthesisMode={synthesisMode}
          setSynthesisMode={setSynthesisMode}
          deliveryMode={deliveryMode}
          setDeliveryMode={setDeliveryMode}
          latency={latency}
          setLatency={setLatency}
          cost={cost}
          setCost={setCost}
          quality={quality}
          setQuality={setQuality}
          retryOnWorkerLoss={retryOnWorkerLoss}
          setRetryOnWorkerLoss={setRetryOnWorkerLoss}
        />
      </div>
    </div>
  );
}
