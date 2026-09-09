import { lazy, Suspense, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ApiError,
  createConversation,
  decideTaskApproval,
  deleteConversation,
  deleteConversationAttachment,
  friendlyApiError,
  listUserModelServices,
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
  ModelSelection,
  Planner,
  Project,
  RunResult,
  Scheduler,
  SynthesisMode,
  Task,
  Tool,
  UserModelService,
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
  messagesLoading,
  messagesLoadError,
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
  messagesLoading: boolean;
  messagesLoadError: string;
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

  const messageScrollRef = useRef<HTMLDivElement | null>(null);

  const [showModelPicker, setShowModelPicker] = useState(false);

  const [modelServices, setModelServices] = useState<UserModelService[]>([]);
  const [modelSelection, setModelSelection] = useState<ModelSelection>({ mode: "auto" });

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

  // Long-running direct streams belong to the conversation that submitted
  // them. Keep the latest active conversation id outside the async closure so
  // late deltas/status/error tails from a background conversation cannot write
  // into the currently visible Workspace after the user switches threads.
  const activeConversationIdRef = useRef<number | null>(current?.id ?? null);
  activeConversationIdRef.current = current?.id ?? null;

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

  const persistedLatestRunTask =
    latestRun
      ? tasks.find((task) => task.id === latestRun.task.id) ?? null
      : null;

  const latestWaitingTask =
    latestRun &&
    isWaitingStatus(latestRun.status) &&
    (persistedLatestRunTask == null ||
      isWaitingStatus(persistedLatestRunTask.status))
      ? persistedLatestRunTask ?? latestRun.task
      : null;

  // The persisted server projection is authoritative. A local RunResult can
  // remain AUTH_REQUIRED after another tab/retry already changed the task, and
  // showing that stale approval card causes a guaranteed 409 on confirmation.
  const waitingTask =
    persistedWaitingTask ??
    latestWaitingTask;

  useEffect(() => {
    let active = true;
    void listUserModelServices()
      .then((items) => {
        if (!active) return;
        setModelServices(items);
        setModelSelection((currentSelection) => {
          if (currentSelection.mode !== "manual" || !currentSelection.serviceId) return currentSelection;
          const stillAvailable = items.some(
            (item) => item.id === currentSelection.serviceId && item.enabled,
          );
          return stillAvailable ? currentSelection : { mode: "auto" };
        });
      })
      .catch(() => {
        if (active) setModelServices([]);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!showModelPicker) {
      return;
    }

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setShowModelPicker(false);
      }
    };

    window.addEventListener("keydown", closeOnEscape);

    return () => {
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [showModelPicker]);

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
      // A conversation boundary is also a composer/runtime boundary.
      // Never carry a failed prompt, attachment preview, streamed answer, or
      // resume state into a newly created/opened conversation.
      setText("");
      setPendingPrompt("");
      setPendingAttachments([]);
      setStreamingAnswer("");
      setStreamingPhase("");
      setAttachments((items) => {
        for (const item of items) {
          if (item.previewUrl) {
            URL.revokeObjectURL(item.previewUrl);
          }
        }
        return [];
      });
      setResumeText("");
      setResumeError("");
      setError("");
      setShowDetails(false);
      setDetailsResult(null);
      setShowSettings(false);
      setShowModelPicker(false);
    },
    [current?.id],
  );

  const latestMessageId =
    messages.length > 0
      ? messages[messages.length - 1]?.id ?? null
      : null;

  useLayoutEffect(
    () => {
      const scrollNode =
        messageScrollRef.current;

      if (!scrollNode) {
        return;
      }

      // Entering Workspace or loading/switching a conversation should land on
      // the newest persisted message instead of the beginning of the thread.
      scrollNode.scrollTop =
        scrollNode.scrollHeight;
    },
    [
      current?.id,
      messages.length,
      latestMessageId,
    ],
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

    // Conversation creation (and optional project assignment above) is the
    // authoritative mutation. Select it immediately; sidebar/project
    // projections are best-effort follow-up work and must never prevent an
    // already-created conversation from becoming current. In particular, a
    // transient project-list failure must not leave a new conversation visible
    // in Recent while Workspace remains attached to the previous thread.
    setCurrent(
      conversation,
    );

    setSelectedProjectId(
      null,
    );

    setLatestRunState(
      null,
    );

    void Promise.allSettled([
      reloadConversations(),
      reloadProjects(),
    ]);
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

    let submittedConversation = current;

    try {
      setBusy(true);
      setError("");

      let conversation = submittedConversation;
      if (!conversation) {
        conversation = await createConversation("新会话");
        submittedConversation = conversation;
        activeConversationIdRef.current = conversation.id;
        setCurrent(conversation);
        await reloadConversations();
      } else {
        submittedConversation = conversation;
      }

      // Capture the submission owner as an immutable scalar before any async
      // callbacks are created. TypeScript does not preserve the local
      // `conversation != null` narrowing inside closures, and more
      // importantly ownership must stay bound to the conversation that
      // accepted this submission even if the local conversation object is
      // later replaced by an auto-title response.
      const submissionConversationId = conversation.id;

      const input = {
        conversationId: submissionConversationId,
        task: submittedPrompt,
        scheduler,
        planner,
        executionMode,
        synthesisMode,
        deliveryMode,
        modelSelection,
        maxLatencyMs: latency,
        maxCost: cost,
        minQuality: quality,
        retryOnWorkerLoss: deliveryMode === "durable" ? retryOnWorkerLoss : false,
        attachmentIds: submittedAttachments.map((item) => item.server!.id),
      };

      const isSubmissionConversationActive = () =>
        activeConversationIdRef.current === submissionConversationId;

      const result = deliveryMode === "direct"
        ? await runTaskStream(input, {
            onDelta: (delta) => {
              if (!isSubmissionConversationActive()) return;
              setStreamingPhase("正在生成回答…");
              setStreamingAnswer((currentText) => currentText + delta);
            },
            onStatus: (message) => {
              if (!isSubmissionConversationActive()) return;
              setStreamingPhase(message);
            },
          })
        : await runTask(input);

      setLatestRunState({ conversationId: submissionConversationId, result });

      if (UNTITLED_TITLES.has(conversation.title)) {
        try {
          const renamed = await renameConversation(conversation.id, deriveConversationTitle(submittedPrompt));
          conversation = renamed;
          // renameConversation is already responsible for updating the active
          // conversation only when that conversation is still current. Never
          // force the renamed submission conversation back into current here:
          // the user may have created/selected another conversation while the
          // auto-title request was still in flight.
        } catch {
          // Auto-title failure must never fail the task itself.
        }
      }

      // Message history is a visible projection of the active conversation.
      // A background submission may finish and persist successfully after the
      // user switches elsewhere, but it must not load its messages into the
      // active thread. When the user returns, the normal conversation switch
      // path reloads that conversation from authoritative server history.
      const completionRefreshes: Promise<unknown>[] = [
        reloadTasks(),
        reloadConversations(),
      ];
      if (isSubmissionConversationActive()) {
        completionRefreshes.unshift(reloadMessages(submissionConversationId));
      }
      await Promise.all(completionRefreshes);

      submittedAttachments.forEach((item) => {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      });
      if (isSubmissionConversationActive()) {
        setPendingPrompt("");
        setPendingAttachments([]);
        setStreamingAnswer("");
        setStreamingPhase("");
      }
    } catch (e) {
      const submittedConversationIsActive =
        submittedConversation != null &&
        activeConversationIdRef.current === submittedConversation.id;

      if (submittedConversationIsActive) {
        setError(friendlyApiError(e, "任务提交失败，请稍后重试。"));
      }

      const serverAcceptedStreamFailure =
        e instanceof ApiError &&
        e.code === 50210;

      if (
        serverAcceptedStreamFailure &&
        submittedConversation
      ) {
        // run-stream errors arrive only after Go accepted the request and
        // persisted the user turn. Refresh authoritative server history and do
        // not restore the same prompt into the composer, otherwise a retry
        // creates duplicate user messages (for example repeated bare "A").
        const failureRefreshes: Promise<unknown>[] = [
          reloadTasks(),
          reloadConversations(),
        ];
        if (submittedConversationIsActive) {
          failureRefreshes.unshift(reloadMessages(submittedConversation.id));
        }
        await Promise.allSettled(failureRefreshes);
        if (submittedConversationIsActive) {
          setText("");
        }
        submittedAttachments.forEach((item) => {
          if (item.previewUrl) {
            URL.revokeObjectURL(item.previewUrl);
          }
        });
        if (submittedConversationIsActive) {
          setAttachments([]);
        }
      } else if (submittedConversationIsActive) {
        // Transport/preflight failures may happen before the server persists the
        // request, so retain the local draft only when its submitting
        // conversation is still visible. Never restore a background
        // conversation's prompt/attachments into another active conversation.
        setText((currentText) => currentText.trim() ? currentText : submittedPrompt);
        setAttachments((currentItems) => currentItems.length ? currentItems : submittedAttachments);
      }

      if (submittedConversationIsActive) {
        setPendingPrompt("");
        setPendingAttachments([]);
        setStreamingAnswer("");
        setStreamingPhase("");
      }
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
      // A 409 can mean the task already advanced between rendering the card and
      // clicking it. Refresh server state and discard the stale local waiting
      // snapshot instead of leaving a permanently unusable approval panel.
      await Promise.allSettled([
        reloadTasks(),
        reloadMessages(current.id),
      ]);
      setLatestRunState(null);
      setResumeError(friendlyApiError(e, "审批操作失败，已刷新最新任务状态。"));
    } finally {
      setResumeBusy(false);
    }
  };

  const enabledModelServices =
    modelServices.filter(
      (service) =>
        service.enabled,
    );

  const selectedModelService =
    modelSelection.mode === "manual" &&
    modelSelection.serviceId
      ? enabledModelServices.find(
          (service) =>
            service.id ===
            modelSelection.serviceId,
        ) ?? null
      : null;

  const modelPickerLabel =
    selectedModelService?.modelName?.trim() ||
    selectedModelService?.name?.trim() ||
    "自动选择";

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
        <section
          className="workspace-core"
          data-testid="workspace-conversation"
          data-conversation-id={current?.id ?? ""}
          data-messages-state={messagesLoading ? "loading" : messagesLoadError ? "error" : "ready"}
          aria-busy={messagesLoading}
        >
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

          <div className="workspace-scroll" ref={messageScrollRef}>
            <div className="workspace-scroll-inner">
              <MessageHistory
                messages={messages}
                messagesLoading={messagesLoading}
                messagesLoadError={messagesLoadError}
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
                  data-testid="workspace-composer"
                  value={text}
                  rows={3}
                  placeholder={busy ? "可以继续输入下一条消息…" : "描述目标，AgentMesh 会自动规划并执行..."}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (
                      e.key !== "Enter" ||
                      e.shiftKey ||
                      e.nativeEvent.isComposing
                    ) {
                      return;
                    }

                    e.preventDefault();

                    if (!busy) {
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
                  <div className="composer-footer-left">
                    <div className={`composer-model-menu ${showModelPicker ? "open" : ""}`}>
                      <button
                        className="composer-model-trigger"
                        type="button"
                        aria-haspopup="menu"
                        aria-expanded={showModelPicker}
                        title={
                          selectedModelService
                            ? `${selectedModelService.name} · ${selectedModelService.modelName}`
                            : "自动选择模型"
                        }
                        onClick={() =>
                          setShowModelPicker(
                            (value) =>
                              !value,
                          )
                        }
                      >
                        <span className="composer-model-trigger-label">
                          {modelPickerLabel}
                        </span>

                        <span
                          className="composer-model-trigger-chevron"
                          aria-hidden="true"
                        >
                          ⌄
                        </span>
                      </button>

                      {showModelPicker && (
                        <>
                          <button
                            className="composer-model-menu-backdrop"
                            type="button"
                            aria-label="关闭模型选择"
                            onClick={() =>
                              setShowModelPicker(
                                false,
                              )
                            }
                          />

                          <div
                            className="composer-model-popover"
                            role="menu"
                            aria-label="选择模型"
                          >
                            <div className="composer-model-popover-title">
                              选择模型
                            </div>

                            <button
                              className={`composer-model-option ${
                                modelSelection.mode === "auto"
                                  ? "active"
                                  : ""
                              }`}
                              type="button"
                              role="menuitemradio"
                              aria-checked={
                                modelSelection.mode === "auto"
                              }
                              onClick={() => {
                                setModelSelection({
                                  mode: "auto",
                                });
                                setShowModelPicker(false);
                              }}
                            >
                              <span className="composer-model-option-main">
                                <strong>
                                  自动选择
                                </strong>

                                <small>
                                  根据任务能力、质量、延迟和成本自动路由
                                </small>
                              </span>

                              {modelSelection.mode === "auto" && (
                                <span
                                  className="composer-model-option-check"
                                  aria-hidden="true"
                                >
                                  ✓
                                </span>
                              )}
                            </button>

                            {enabledModelServices.length > 0 && (
                              <div className="composer-model-option-divider" />
                            )}

                            {enabledModelServices.map(
                              (service) => {
                                const active =
                                  modelSelection.mode === "manual" &&
                                  modelSelection.serviceId === service.id;

                                return (
                                  <button
                                    key={service.id}
                                    className={`composer-model-option ${
                                      active
                                        ? "active"
                                        : ""
                                    }`}
                                    type="button"
                                    role="menuitemradio"
                                    aria-checked={active}
                                    onClick={() => {
                                      setModelSelection({
                                        mode: "manual",
                                        serviceId: service.id,
                                      });
                                      setShowModelPicker(false);
                                    }}
                                  >
                                    <span className="composer-model-option-main">
                                      <strong>
                                        {service.name}
                                      </strong>

                                      <small>
                                        {service.modelName}
                                        {" · "}
                                        个人模型服务
                                      </small>
                                    </span>

                                    {active && (
                                      <span
                                        className="composer-model-option-check"
                                        aria-hidden="true"
                                      >
                                        ✓
                                      </span>
                                    )}
                                  </button>
                                );
                              },
                            )}

                            {enabledModelServices.length === 0 && (
                              <div className="composer-model-empty">
                                暂无已启用的个人模型服务，可在“模型设置”中添加。
                              </div>
                            )}
                          </div>
                        </>
                      )}
                    </div>

                    <button
                      className="composer-settings-button composer-settings-button-compact"
                      onClick={() => {
                        setShowModelPicker(false);
                        setShowSettings(true);
                      }}
                      type="button"
                      title="执行偏好"
                    >
                      <span className="composer-settings-icon">
                        <Icon
                          name="tool"
                          size={14}
                        />
                      </span>

                      <span>
                        执行偏好
                      </span>
                    </button>
                  </div>

                  <div className="composer-footer-right">
                    <button
                      className="primary-button run-button"
                      data-testid="workspace-submit"
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
                  </div>
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
            <aside
              className="workspace-details-drawer"
              data-testid="run-details-drawer"
              role="dialog"
              aria-modal="true"
              aria-label="运行详情"
            >
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
