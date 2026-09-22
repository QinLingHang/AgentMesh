import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ApiError,
  createConversation,
  decideTaskApproval,
  deleteConversation,
  deleteConversationAttachment,
  friendlyApiError,
  listUserModelServices,
  listKnowledgeBases,
  resumeTask,
  runTask,
  runTaskStream,
  subscribeDurableTaskEvents,
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
  KnowledgeBase,
  ModelSelection,
  Planner,
  Project,
  RagMode,
  RagScope,
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

type MessageHistoryAnchor = {
  messageId: number | null;
  top: number | null;
  scrollHeight: number;
  scrollTop: number;
  fallbackApplied: boolean;
  dirty: boolean;
  stableFrames: number;
  settleFrames: number;
  settleStartedAt: number | null;
  lastMutationAt: number | null;
};

const MESSAGE_ANCHOR_SELECTOR =
  '[data-testid="message-user"][data-message-id], [data-testid="message-assistant"][data-message-id]';

const MESSAGE_ANCHOR_TOLERANCE_PX = 1;
const MESSAGE_ANCHOR_STABLE_FRAMES = 3;
const MESSAGE_ANCHOR_MAX_SETTLE_FRAMES = 30;
const MESSAGE_ANCHOR_QUIET_MS = 120;
const MESSAGE_ANCHOR_MAX_SETTLE_MS = 500;

function latestTaskForConversation(
  tasks: Task[],
  conversationId: number,
): Task | null {
  let latest: Task | null = null;

  for (const task of tasks) {
    if (task.conversationId !== conversationId) {
      continue;
    }

    if (latest == null || task.id > latest.id) {
      latest = task;
    }
  }

  return latest;
}

export function Workspace({
  conversations,
  projects,
  current,
  setCurrent,
  messages,
  messagesLoading,
  messagesLoadError,
  messageHasMore,
  olderMessagesLoading,
  loadOlderMessages,
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
  messageHasMore: boolean;
  olderMessagesLoading: boolean;
  loadOlderMessages: () => Promise<void>;
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
  const messageScrollInnerRef = useRef<HTMLDivElement | null>(null);
  const messageScrollFrameRef = useRef<number | null>(null);
  const messageScrollProgrammaticRef = useRef(false);
  const messageHistoryAnchorRef = useRef<MessageHistoryAnchor | null>(null);
  const shouldAutoFollowMessagesRef = useRef(true);
  const lastScrollConversationIdRef = useRef<number | null>(null);

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
      "auto",
    );

  const [ragMode, setRagMode] =
    useState<RagMode>("AUTO");

  const [ragScopes, setRagScopes] =
    useState<RagScope[]>(["PROJECT"]);

  // Knowledge selection is optional. An empty list means AUTO discovery
  // restricted by the selected scopes, NOT access to every global base.
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKnowledgeBaseIds, setSelectedKnowledgeBaseIds] = useState<number[]>([]);
  const [knowledgeCatalogError, setKnowledgeCatalogError] = useState("");

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

  // Same-conversation submissions also need turn ownership. A late result from
  // an older turn must not replace the latest run/approval state after the user
  // has already submitted another turn in this conversation.
  const submissionEpochByConversationRef = useRef<Map<number, number>>(new Map());

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

  useEffect(() => {
    if (!showSettings || ragMode === "OFF") return;
    let active = true;
    listKnowledgeBases().then((bases) => {
      if (!active) return;
      setKnowledgeBases(bases);
      setKnowledgeCatalogError("");
    }).catch(() => {
      if (active) setKnowledgeCatalogError("知识库目录读取失败，请重试。实际权限仍由服务端判定。");
    });
    return () => { active = false; };
  }, [showSettings, ragMode]);

  const activeProjectId = projects.find(
    (project) => current != null && project.conversationIds.includes(current.id),
  )?.id;
  const selectableKnowledgeBases = knowledgeBases.filter((base) =>
    (base.scope === "PROJECT" && ragScopes.includes("PROJECT") && base.projectId === activeProjectId) ||
    (base.scope === "GLOBAL" && ragScopes.includes("USER_GLOBAL")),
  );

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

  const latestConversationTask =
    current
      ? latestTaskForConversation(
          tasks,
          current.id,
        )
      : null;

  // Approval/input state is actionable only when that waiting task is still the
  // newest task in the conversation. If a newer user turn exists, any older
  // pending approval belongs to history and must never be rendered in the
  // current composer.
  const persistedWaitingTask =
    latestConversationTask &&
    isWaitingStatus(
      latestConversationTask.status,
    )
      ? latestConversationTask
      : null;

  const persistedLatestRunTask =
    latestRun
      ? tasks.find((task) => task.id === latestRun.task.id) ?? null
      : null;

  const latestWaitingTask =
    latestRun &&
    isWaitingStatus(latestRun.status) &&
    (latestConversationTask == null ||
      latestConversationTask.id === latestRun.task.id) &&
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

  const forceMessageScrollBottom = useCallback((scrollNode: HTMLDivElement) => {
    // workspace.css previously used scroll-behavior:smooth. That made the
    // browser emit intermediate scroll events while the initial history was
    // still settling; those events were mistaken for an intentional user
    // scroll and disabled auto-follow before the true bottom was reached.
    //
    // Always use an immediate numeric scroll for ownership/restoration
    // positioning. Smooth scrolling, if we ever want it for an explicit
    // "back to bottom" button, must be opt-in and must not be used here.
    const bottom = Math.max(
      0,
      scrollNode.scrollHeight - scrollNode.clientHeight,
    );
    scrollNode.scrollTop = bottom;
  }, []);

  const scrollMessagesToBottom = useCallback(() => {
    // Loading an older page temporarily owns the viewport. Any late
    // auto-follow callback from conversation restoration/ResizeObserver must
    // yield until the prepend anchor transaction has completed.
    if (messageHistoryAnchorRef.current != null) {
      return;
    }

    const scrollNode = messageScrollRef.current;
    if (!scrollNode) {
      return;
    }

    if (messageScrollFrameRef.current != null) {
      window.cancelAnimationFrame(messageScrollFrameRef.current);
      messageScrollFrameRef.current = null;
    }

    messageScrollProgrammaticRef.current = true;
    forceMessageScrollBottom(scrollNode);

    // Settle across several layout frames. Conversation restoration can change
    // both sides of the equation:
    // 1. Markdown / attachments / historical run metadata can grow scrollHeight.
    // 2. Composer / toolbar layout can shrink clientHeight.
    //
    // Repositioning only once (FIX10) covered the first synchronous commit but
    // could still finish above the real bottom after either late layout change.
    let remainingFrames = 3;

    const settle = () => {
      const settledNode = messageScrollRef.current;
      if (!settledNode) {
        messageScrollProgrammaticRef.current = false;
        messageScrollFrameRef.current = null;
        return;
      }

      forceMessageScrollBottom(settledNode);

      if (remainingFrames > 0) {
        remainingFrames -= 1;
        messageScrollFrameRef.current =
          window.requestAnimationFrame(settle);
        return;
      }

      messageScrollFrameRef.current =
        window.requestAnimationFrame(() => {
          const finalNode = messageScrollRef.current;
          if (finalNode) {
            forceMessageScrollBottom(finalNode);
          }
          messageScrollProgrammaticRef.current = false;
          messageScrollFrameRef.current = null;
        });
    };

    messageScrollFrameRef.current =
      window.requestAnimationFrame(settle);
  }, [forceMessageScrollBottom]);

  const handleMessageScroll = useCallback(() => {
    if (messageScrollProgrammaticRef.current) {
      return;
    }

    const scrollNode = messageScrollRef.current;
    if (!scrollNode) {
      return;
    }

    const distanceFromBottom =
      scrollNode.scrollHeight - scrollNode.scrollTop - scrollNode.clientHeight;
    shouldAutoFollowMessagesRef.current = distanceFromBottom <= 96;
  }, []);

  const cancelScheduledMessageScroll = useCallback(() => {
    if (messageScrollFrameRef.current != null) {
      window.cancelAnimationFrame(messageScrollFrameRef.current);
      messageScrollFrameRef.current = null;
    }
  }, []);

  const captureVisibleMessageAnchor = useCallback(
    (scrollNode: HTMLDivElement): MessageHistoryAnchor => {
      const viewport = scrollNode.getBoundingClientRect();
      const messageNodes =
        Array.from(
          scrollNode.querySelectorAll<HTMLElement>(
            MESSAGE_ANCHOR_SELECTOR,
          ),
        );

      const visibleNode =
        messageNodes.find((node) => {
          const rect =
            node.getBoundingClientRect();

          return (
            rect.bottom >
              viewport.top &&
            rect.top <
              viewport.bottom
          );
        }) ?? null;

      const rawMessageId =
        visibleNode?.getAttribute(
          "data-message-id",
        ) ?? "";
      const parsedMessageId =
        Number(rawMessageId);

      return {
        messageId:
          visibleNode &&
          Number.isFinite(
            parsedMessageId,
          ) &&
          parsedMessageId > 0
            ? parsedMessageId
            : null,
        top:
          visibleNode
            ? visibleNode
                .getBoundingClientRect()
                .top
            : null,
        scrollHeight:
          scrollNode.scrollHeight,
        scrollTop:
          scrollNode.scrollTop,
        fallbackApplied: false,
        dirty: true,
        stableFrames: 0,
        settleFrames: 0,
        settleStartedAt: null,
        lastMutationAt: null,
      };
    },
    [],
  );

  const preserveOlderHistoryAnchor = useCallback(() => {
    const anchor =
      messageHistoryAnchorRef.current;
    const scrollNode =
      messageScrollRef.current;

    if (!anchor || !scrollNode) {
      return null;
    }

    // FIX15: the concrete durable message is authoritative. Total scroll-height
    // growth is only a missing-anchor fallback because loading older rows can
    // legitimately reorder already-rendered turns.
    if (
      anchor.messageId != null &&
      anchor.top != null
    ) {
      const anchorElement =
        scrollNode.querySelector<HTMLElement>(
          `[data-testid="message-user"][data-message-id="${anchor.messageId}"], ` +
            `[data-testid="message-assistant"][data-message-id="${anchor.messageId}"]`,
        );

      if (anchorElement) {
        const nextTop =
          anchorElement
            .getBoundingClientRect()
            .top;
        const delta =
          nextTop - anchor.top;

        if (
          Math.abs(delta) >
          MESSAGE_ANCHOR_TOLERANCE_PX
        ) {
          scrollNode.scrollTop += delta;
        }

        return Math.abs(delta);
      }
    }

    // A missing/deleted anchor should never send the reader to the bottom.
    // Apply the legacy height fallback once, then keep the transaction alive
    // until the same coordinator observes a quiet/stable window or times out.
    if (!anchor.fallbackApplied) {
      const addedHeight =
        Math.max(
          0,
          scrollNode.scrollHeight -
            anchor.scrollHeight,
        );
      scrollNode.scrollTop =
        anchor.scrollTop +
        addedHeight;
      anchor.fallbackApplied = true;
    }

    return null;
  }, []);

  const releaseOlderHistoryAnchor = useCallback(() => {
    if (messageScrollFrameRef.current != null) {
      window.cancelAnimationFrame(
        messageScrollFrameRef.current,
      );
      messageScrollFrameRef.current = null;
    }

    messageHistoryAnchorRef.current = null;
    messageScrollProgrammaticRef.current = false;
  }, []);

  const scheduleOlderHistoryAnchorSettlement = useCallback(() => {
    if (
      messageHistoryAnchorRef.current == null ||
      messageScrollFrameRef.current != null
    ) {
      return;
    }

    const settleAnchor = () => {
      messageScrollFrameRef.current = null;

      const anchor =
        messageHistoryAnchorRef.current;

      if (anchor == null) {
        messageScrollProgrammaticRef.current = false;
        return;
      }

      const now =
        window.performance.now();

      if (anchor.settleStartedAt == null) {
        anchor.settleStartedAt = now;
      }

      anchor.settleFrames += 1;

      const wasDirty =
        anchor.dirty;
      anchor.dirty = false;

      const residual =
        preserveOlderHistoryAnchor();

      const corrected =
        residual != null &&
        residual >
          MESSAGE_ANCHOR_TOLERANCE_PX;

      const stableMeasurement =
        residual == null
          ? anchor.fallbackApplied
          : residual <=
            MESSAGE_ANCHOR_TOLERANCE_PX;

      if (
        wasDirty ||
        corrected ||
        !stableMeasurement
      ) {
        anchor.stableFrames = 0;
      } else {
        anchor.stableFrames += 1;
      }

      const quietSince =
        anchor.lastMutationAt ??
        anchor.settleStartedAt;
      const quietFor =
        now - quietSince;
      const elapsed =
        now - anchor.settleStartedAt;

      const stable =
        anchor.stableFrames >=
          MESSAGE_ANCHOR_STABLE_FRAMES &&
        quietFor >=
          MESSAGE_ANCHOR_QUIET_MS;

      const timedOut =
        anchor.settleFrames >=
          MESSAGE_ANCHOR_MAX_SETTLE_FRAMES ||
        elapsed >=
          MESSAGE_ANCHOR_MAX_SETTLE_MS;

      if (stable || timedOut) {
        // One final same-element measurement closes any residual introduced in
        // the last observed layout frame. Do not re-enable newest-message
        // following: after loading older history the reader owns the viewport.
        preserveOlderHistoryAnchor();
        releaseOlderHistoryAnchor();
        return;
      }

      messageScrollFrameRef.current =
        window.requestAnimationFrame(
          settleAnchor,
        );
    };

    messageScrollFrameRef.current =
      window.requestAnimationFrame(
        settleAnchor,
      );
  }, [
    preserveOlderHistoryAnchor,
    releaseOlderHistoryAnchor,
  ]);

  const markOlderHistoryAnchorDirty = useCallback(() => {
    const anchor =
      messageHistoryAnchorRef.current;

    if (anchor == null) {
      return;
    }

    anchor.dirty = true;
    anchor.stableFrames = 0;
    anchor.lastMutationAt =
      window.performance.now();

    scheduleOlderHistoryAnchorSettlement();
  }, [
    scheduleOlderHistoryAnchorSettlement,
  ]);

  const handleMessageScrollIntent = useCallback(() => {
    // Pointer/wheel/touch interaction means the reader is taking control of
    // the viewport. Abort any in-flight automatic anchor transaction rather
    // than fighting the reader. The normal scroll handler will re-enable
    // follow if the reader actually returns close to the bottom.
    releaseOlderHistoryAnchor();
  }, [releaseOlderHistoryAnchor]);

  const handleLoadOlderHistory = useCallback(async () => {
    const scrollNode = messageScrollRef.current;
    if (!scrollNode) {
      await loadOlderMessages();
      return;
    }

    // Enter explicit viewport ownership before the async page request starts.
    // FIX15 keeps one post-commit coordinator: useLayoutEffect may make the
    // first correction, ResizeObserver only marks geometry dirty, and rAF owns
    // all settling/release decisions.
    cancelScheduledMessageScroll();
    shouldAutoFollowMessagesRef.current = false;
    messageScrollProgrammaticRef.current = true;
    messageHistoryAnchorRef.current =
      captureVisibleMessageAnchor(
        scrollNode,
      );

    try {
      await loadOlderMessages();
    } catch (error) {
      releaseOlderHistoryAnchor();
      throw error;
    }

    markOlderHistoryAnchorDirty();
  }, [
    cancelScheduledMessageScroll,
    captureVisibleMessageAnchor,
    loadOlderMessages,
    markOlderHistoryAnchorDirty,
    releaseOlderHistoryAnchor,
  ]);

  useLayoutEffect(() => {
    const conversationId = current?.id ?? null;
    const conversationChanged =
      lastScrollConversationIdRef.current !== conversationId;

    if (conversationChanged) {
      lastScrollConversationIdRef.current = conversationId;
      releaseOlderHistoryAnchor();
      shouldAutoFollowMessagesRef.current = true;
    }

    if (messagesLoading) {
      return;
    }

    // React has committed the new message DOM but has not painted yet. Apply
    // one immediate concrete-element correction, then let the single rAF
    // coordinator own all later settling/release work.
    if (messageHistoryAnchorRef.current != null) {
      preserveOlderHistoryAnchor();
      markOlderHistoryAnchorDirty();
      return;
    }

    // Opening, restoring or switching a conversation always lands at the true
    // end. Afterwards we only follow new/streaming content while the reader
    // remains near the bottom; scrolling upward is explicit user intent.
    if (conversationChanged || shouldAutoFollowMessagesRef.current) {
      scrollMessagesToBottom();
    }
  }, [
    current?.id,
    latestMessageId,
    messages.length,
    messagesLoading,
    pendingPrompt,
    streamingAnswer,
    markOlderHistoryAnchorDirty,
    preserveOlderHistoryAnchor,
    releaseOlderHistoryAnchor,
    scrollMessagesToBottom,
  ]);

  useEffect(() => {
    const contentNode = messageScrollInnerRef.current;
    const scrollNode = messageScrollRef.current;
    if (
      !contentNode ||
      !scrollNode ||
      typeof ResizeObserver === "undefined"
    ) {
      return undefined;
    }

    // ResizeObserver is notification-only during an older-history transaction.
    // It never writes scrollTop itself; doing so would create an independent
    // correction writer racing useLayoutEffect/rAF. The coordinator re-measures
    // the durable anchor on the next animation frame.
    const observer = new ResizeObserver(() => {
      if (messageHistoryAnchorRef.current != null) {
        markOlderHistoryAnchorDirty();
        return;
      }

      if (shouldAutoFollowMessagesRef.current) {
        scrollMessagesToBottom();
      }
    });

    observer.observe(contentNode);
    observer.observe(scrollNode);

    return () => observer.disconnect();
  }, [
    current?.id,
    markOlderHistoryAnchorDirty,
    scrollMessagesToBottom,
  ]);


  useEffect(() => () => {
    if (messageScrollFrameRef.current != null) {
      window.cancelAnimationFrame(messageScrollFrameRef.current);
      messageScrollFrameRef.current = null;
    }
    messageHistoryAnchorRef.current = null;
    messageScrollProgrammaticRef.current = false;
  }, []);


  // A browser reload loses the transient latestRunState, but MySQL-backed
  // tasks are still available. Recover a pending durable task from the active
  // conversation's newest persisted task; never revive an older task after a
  // newer turn supersedes it.
  const persistedDurableTask = latestConversationTask &&
    latestConversationTask.deliveryMode === "durable" &&
    (latestConversationTask.status === "QUEUED" || latestConversationTask.status === "RUNNING")
      ? latestConversationTask : null;
  const transientDurableTask = latestRun &&
    latestRun.task.deliveryMode === "durable" &&
    (latestRun.status === "QUEUED" || latestRun.status === "RUNNING") &&
    (latestConversationTask == null ||
      (latestConversationTask.id === latestRun.task.id &&
       (latestConversationTask.status === "QUEUED" || latestConversationTask.status === "RUNNING")))
      ? latestRun.task : null;
  const activeDurableTask = persistedDurableTask ?? transientDurableTask;
  const durablePending = activeDurableTask != null;

  useEffect(
    () => {
      if (!durablePending || !current || !activeDurableTask) return;
      const taskId = activeDurableTask.id;
      const conversationId = current.id;
      const controller = new AbortController();
      let stopped = false;
      let streaming = false;
      let cursor = 0;
      const refresh = () => {
        if (stopped) return;
        void Promise.allSettled([
          reloadTasks(),
          reloadMessages(conversationId),
          reloadConversations(),
        ]);
      };
      refresh();
      // Poll only if the event stream is disconnected. This is also the
      // compatibility fallback for servers that predate P22 SSE.
      const fallback = window.setInterval(() => {
        if (!streaming) refresh();
      }, 1000);
      void (async () => {
        while (!stopped) {
          try {
            const next = await subscribeDurableTaskEvents(
              taskId, cursor,
              (event) => {
                if (stopped) return;
                cursor = Math.max(cursor, event.sequence);
                if (activeConversationIdRef.current === conversationId) {
                  const phaseNames: Record<string, string> = {
                    task: "任务", planner: "规划", scheduler: "调度",
                    agent: "Agent", tool: "工具", mcp: "MCP",
                    rag: "知识检索", knowledge: "知识", memory: "记忆", model: "模型",
                  };
                  if (event.eventType === "trace" && event.phase && event.phaseStatus) {
                    // Do not display remote trace titles or details in Workspace.
                    setStreamingPhase(`${phaseNames[event.phase] ?? "执行"}：${event.phaseStatus}`);
                  } else {
                    setStreamingPhase(`任务状态：${event.status}`);
                  }
                }
                // A trace is a progress hint, not an authoritative task status
                // transition. Avoid multiple task/history fetches per tool step.
                if (event.eventType !== "trace") refresh();
              },
              controller.signal,
              () => { streaming = true; },
            );
            cursor = Math.max(cursor, next.cursor);
            streaming = false;
            if (next.terminal) {
              refresh();
              break;
            }
          } catch {
            // Never resubmit a task to repair a broken SSE connection.
            // Authoritative task/message polling remains available.
            streaming = false;
            if (controller.signal.aborted) break;
          }
          if (!stopped) await new Promise<void>((resolve) => window.setTimeout(resolve, 1500));
        }
      })();
      return () => {
        stopped = true;
        controller.abort();
        window.clearInterval(fallback);
      };
    },
    [
      durablePending,
      activeDurableTask?.id,
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
    shouldAutoFollowMessagesRef.current = true;
    scrollMessagesToBottom();
    setPendingPrompt(submittedPrompt);
    setPendingAttachments(submittedAttachmentMetadata);
    setStreamingAnswer("");
    setStreamingPhase("正在连接模型…");
    setText("");
    setAttachments([]);

    let submittedConversation = current;
    let submissionOwnerConversationId: number | null =
      submittedConversation?.id ?? null;
    let submissionEpoch: number | null = null;

    const isLatestSubmissionOwner = () => {
      if (submissionOwnerConversationId == null || submissionEpoch == null) {
        return true;
      }

      return (
        submissionEpochByConversationRef.current.get(
          submissionOwnerConversationId,
        ) === submissionEpoch
      );
    };

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
      submissionOwnerConversationId = submissionConversationId;
      submissionEpoch =
        (submissionEpochByConversationRef.current.get(
          submissionConversationId,
        ) ?? 0) + 1;
      submissionEpochByConversationRef.current.set(
        submissionConversationId,
        submissionEpoch,
      );

      const input = {
        conversationId: submissionConversationId,
        task: submittedPrompt,
        scheduler,
        planner,
        executionMode,
        synthesisMode,
        deliveryMode,
        ragPolicy: {
          mode: ragMode,
          scopes: ragScopes,
          selectedKnowledgeBaseIds: selectedKnowledgeBaseIds.filter((id) =>
            selectableKnowledgeBases.some((base) => base.id === id),
          ),
        },
        modelSelection,
        maxLatencyMs: latency,
        maxCost: cost,
        minQuality: quality,
        retryOnWorkerLoss: deliveryMode === "direct" ? false : retryOnWorkerLoss,
        attachmentIds: submittedAttachments.map((item) => item.server!.id),
      };

      const isSubmissionConversationActive = () =>
        activeConversationIdRef.current === submissionConversationId;

      // Exactly one submit request. Go selects the execution mode from the
      // request it actually accepts; a separate preflight risks stale policy
      // and doubles requests in case of retry or connection failure.
      const result = deliveryMode !== "durable"
        ? await runTaskStream(input, {
            onDelta: (delta) => {
              // Keep the active-conversation guard as an explicit first gate.
              // Besides making ownership intent obvious, this preserves the
              // legacy V4.1 source-contract shape without weakening the newer
              // latest-submission epoch guard below.
              if (!isSubmissionConversationActive()) return;
              if (!isLatestSubmissionOwner()) return;
              setStreamingPhase("正在生成回答…");
              setStreamingAnswer((currentText) => currentText + delta);
            },
            onStatus: (message) => {
              if (!isSubmissionConversationActive()) return;
              if (!isLatestSubmissionOwner()) return;
              setStreamingPhase(message);
            },
          })
        : await runTask(input);

      if (isLatestSubmissionOwner()) {
        setLatestRunState({
          conversationId: submissionConversationId,
          result,
        });
      }

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
      if (
        isSubmissionConversationActive() &&
        isLatestSubmissionOwner()
      ) {
        setPendingPrompt("");
        setPendingAttachments([]);
        setStreamingAnswer("");
        setStreamingPhase("");
      }
    } catch (e) {
      const submittedConversationIsActive =
        submittedConversation != null &&
        activeConversationIdRef.current === submittedConversation.id;
      const submittedTurnIsLatest =
        isLatestSubmissionOwner();

      if (submittedConversationIsActive && submittedTurnIsLatest) {
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
        if (submittedConversationIsActive && submittedTurnIsLatest) {
          failureRefreshes.unshift(reloadMessages(submittedConversation.id));
        }
        await Promise.allSettled(failureRefreshes);
        if (submittedConversationIsActive && submittedTurnIsLatest) {
          setText("");
        }
        submittedAttachments.forEach((item) => {
          if (item.previewUrl) {
            URL.revokeObjectURL(item.previewUrl);
          }
        });
        if (submittedConversationIsActive && submittedTurnIsLatest) {
          setAttachments([]);
        }
      } else if (submittedConversationIsActive && submittedTurnIsLatest) {
        // Transport/preflight failures may happen before the server persists the
        // request, so retain the local draft only when its submitting
        // conversation is still visible. Never restore a background
        // conversation's prompt/attachments into another active conversation.
        setText((currentText) => currentText.trim() ? currentText : submittedPrompt);
        setAttachments((currentItems) => currentItems.length ? currentItems : submittedAttachments);
      }

      if (submittedConversationIsActive && submittedTurnIsLatest) {
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

    const approvalTask = waitingTask;
    const approvalConversationId = current.id;

    if (
      approvalTask.conversationId != null &&
      approvalTask.conversationId !== approvalConversationId
    ) {
      setResumeError("该审批已不属于当前会话，已拒绝执行。");
      return;
    }

    try {
      setResumeBusy(true);
      setResumeError("");

      const result = await decideTaskApproval(
        approvalTask.id,
        decision,
      );

      const approvalConversationStillActive =
        activeConversationIdRef.current === approvalConversationId;

      if (approvalConversationStillActive) {
        setLatestRunState({
          conversationId: approvalConversationId,
          result,
        });
      }

      const refreshes: Promise<unknown>[] = [
        reloadTasks(),
        reloadConversations(),
      ];
      if (approvalConversationStillActive) {
        refreshes.unshift(
          reloadMessages(approvalConversationId),
        );
      }
      await Promise.all(refreshes);

      if (
        approvalConversationStillActive &&
        result.status === "COMPLETED"
      ) {
        setShowDetails(false);
        setDetailsResult(null);
      }
    } catch (e) {
      // A 409 can mean the task already advanced between rendering the card and
      // clicking it. Refresh server state and discard the stale local waiting
      // snapshot instead of leaving a permanently unusable approval panel.
      const refreshes: Promise<unknown>[] = [
        reloadTasks(),
      ];
      if (activeConversationIdRef.current === approvalConversationId) {
        refreshes.push(
          reloadMessages(approvalConversationId),
        );
      }
      await Promise.allSettled(refreshes);
      if (activeConversationIdRef.current === approvalConversationId) {
        setLatestRunState(null);
      }
      if (activeConversationIdRef.current === approvalConversationId) {
        setResumeError(friendlyApiError(e, "审批操作失败，已刷新最新任务状态。"));
      }
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

          <div
            className="workspace-scroll"
            ref={messageScrollRef}
            onScroll={handleMessageScroll}
            onWheel={handleMessageScrollIntent}
            onTouchStart={handleMessageScrollIntent}
            onPointerDown={handleMessageScrollIntent}
            data-testid="workspace-message-scroll"
          >
            <div className="workspace-scroll-inner" ref={messageScrollInnerRef}>
              <MessageHistory
                messages={messages}
                messagesLoading={messagesLoading}
                messagesLoadError={messagesLoadError}
                hasMoreHistory={messageHasMore}
                loadingOlderHistory={olderMessagesLoading}
                onLoadOlderHistory={handleLoadOlderHistory}
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
                      data-testid="run-settings-open"
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
          ragMode={ragMode}
          setRagMode={setRagMode}
          ragScopes={ragScopes}
          setRagScopes={setRagScopes}
          knowledgeBases={selectableKnowledgeBases}
          selectedKnowledgeBaseIds={selectedKnowledgeBaseIds}
          setSelectedKnowledgeBaseIds={setSelectedKnowledgeBaseIds}
          knowledgeCatalogError={knowledgeCatalogError}
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
