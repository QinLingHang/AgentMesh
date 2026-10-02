<script setup lang="ts">
import type {
  KnowledgeBase,
  KnowledgeFile,
  Message,
  ProjectRuntimeConfig,
  RunResult,
} from '#/api/agentmesh';

import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue';

import { ElMessage, ElMessageBox } from 'element-plus';

import {
  bindProjectGlobalKnowledgeBase,
  createProject,
  deleteConversation,
  deleteProject,
  deleteProjectKnowledgeFile,
  friendlyApiError,
  getProjectRuntimeConfig,
  listProjectGlobalKnowledgeBindings,
  listProjectKnowledgeFiles,
  moveConversationToProject,
  removeConversationFromProject,
  subscribeDurableTaskEvents,
  unbindProjectGlobalKnowledgeBase,
  updateProject,
  updateProjectRuntimeConfig,
  uploadProjectKnowledgeFile,
} from '#/api/agentmesh';
import EmptyState from '#/components/agentmesh/EmptyState.vue';
import StatusBadge from '#/components/agentmesh/StatusBadge.vue';
import { useAgentMeshResourcesStore } from '#/store/agentmesh-resources';
import { useAgentMeshWorkspaceStore } from '#/store/agentmesh-workspace';

const resources = useAgentMeshResourcesStore();
const workspace = useAgentMeshWorkspaceStore();
const draft = ref('');
const resumeText = ref('');
const fileInput = ref<HTMLInputElement | null>(null);
const messageScroller = ref<HTMLElement | null>(null);
const settingsOpen = ref(false);
const runDetailsOpen = ref(false);
const selectedProjectId = ref<null | number>(null);
const projectDialogOpen = ref(false);
const projectEditingId = ref<null | number>(null);
const projectName = ref('');
const projectDescription = ref('');
const moveDialogOpen = ref(false);
const moveConversationId = ref<null | number>(null);
const moveProjectId = ref<null | number>(null);
const projectRuntimeOpen = ref(false);
const projectRuntimeBusy = ref(false);
const projectKnowledgeInput = ref<HTMLInputElement | null>(null);
const projectRuntime = ref<null | ProjectRuntimeConfig>(null);
const projectKnowledgeOpen = ref(false);
const projectKnowledgeFiles = ref<KnowledgeFile[]>([]);
const projectBindings = ref<KnowledgeBase[]>([]);
const projectBindingSelection = ref<number[]>([]);

const currentProject = computed(
  () =>
    resources.projects.find((item) => item.id === selectedProjectId.value) ??
    null,
);
const conversationGroups = computed(() => {
  const projectMap = new Map<number, typeof resources.conversations>();
  resources.projects.forEach((project) => projectMap.set(project.id, []));
  const ungrouped: typeof resources.conversations = [];
  resources.conversations.forEach((conversation) => {
    const project = resources.projects.find((item) =>
      item.conversationIds.includes(conversation.id),
    );
    if (project) projectMap.get(project.id)?.push(conversation);
    else ungrouped.push(conversation);
  });
  return { projectMap, ungrouped };
});

const latestRun = computed(() => workspace.activeLatestRun);
const traceSteps = computed(() => latestRun.value?.trace ?? []);
const observability = computed(() => latestRun.value?.observability ?? null);
const detailsTrace = computed(() => workspace.detailsRun?.trace ?? []);
const routingEvents = computed(() =>
  detailsTrace.value.filter((event) =>
    ['model_route', 'reschedule', 'routing'].includes(event.kind),
  ),
);
const discoveryEvents = computed(() =>
  detailsTrace.value.filter((event) => event.kind === 'capability_discovery'),
);
const ragEvents = computed(() =>
  detailsTrace.value.filter((event) =>
    ['knowledge', 'rag'].includes(event.kind),
  ),
);
const toolEvents = computed(() =>
  detailsTrace.value.filter((event) =>
    ['approval', 'mcp', 'tool'].includes(event.kind),
  ),
);
const memoryEvents = computed(() =>
  detailsTrace.value.filter((event) =>
    ['memory_forget', 'memory_retrieval', 'memory_write'].includes(event.kind),
  ),
);
const reliabilityEvents = computed(() =>
  detailsTrace.value.filter((event) => event.kind === 'reliability'),
);
function parseDetailRecord(detail: string): Record<string, unknown> {
  try {
    const value = JSON.parse(detail);
    return value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}
function safeRoutingSummary(detail: string) {
  const d = parseDetailRecord(detail);
  const selected =
    d.selectedAgentName ??
    d.selectedRuntimeId ??
    d.to ??
    d.model ??
    d.strategy ??
    '—';
  const score =
    typeof (d.selectedScore ?? d.adaptive_score) === 'number'
      ? Number(d.selectedScore ?? d.adaptive_score).toFixed(4)
      : '—';
  const mode = d.mode ?? d.capability ?? '—';
  let reason = '';
  if (typeof d.reason === 'string') {
    reason = d.reason;
  } else if (Array.isArray(d.reasonCodes)) {
    reason = d.reasonCodes.filter((x) => typeof x === 'string').join(', ');
  }
  return {
    selected: String(selected),
    score,
    mode: String(mode),
    degraded: d.degraded === true,
    reason,
  };
}
function discoverySummary(detail: string) {
  const d = parseDetailRecord(detail);
  const arr = (v: unknown) =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
  return {
    tools: arr(d.selectedTools),
    mcp: arr(d.selectedMCPTools),
    skills: arr(d.selectedSkills),
    knowledge: d.knowledgeSelected === true || d.projectKnowledge === true,
    confidence: typeof d.confidence === 'number' ? d.confidence : null,
  };
}

const waitingTask = computed(() => workspace.waitingTask);
const visibleMessages = computed<Message[]>(() => workspace.messages);
function findActiveDurableTask(conversationId: number) {
  const rows = resources.tasks
    .filter((task) => task.conversationId === conversationId)
    .toSorted((a, b) => b.id - a.id);

  const newest = rows[0] ?? null;
  if (!newest) return null;

  const status = String(newest.status).toUpperCase();

  return newest.deliveryMode === 'durable' &&
    ['QUEUED', 'RUNNING'].includes(status)
    ? newest
    : null;
}

let durableWatchTaskId: null | number = null;
let durableWatchConversationId: null | number = null;

let durableController: AbortController | null = null;
let durableFallback: null | number = null;
let durableWatchToken = 0;

function scrollBottom() {
  nextTick(() => {
    if (messageScroller.value)
      messageScroller.value.scrollTop = messageScroller.value.scrollHeight;
  });
}

async function openConversation(id: number) {
  selectedProjectId.value = null;
  await workspace.openConversation(id);
  scrollBottom();
}

async function createConversation(projectId: null | number = null) {
  const created = await workspace.newConversation();
  if (projectId !== null && projectId !== undefined) {
    await moveConversationToProject(created.id, projectId);
    await resources.refreshProjects();
  }
  selectedProjectId.value = null;
  scrollBottom();
}

async function removeConversation(id: number) {
  await ElMessageBox.confirm('删除后该会话的历史记录将不可恢复。', '删除会话', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  });
  await deleteConversation(id);
  await resources.refreshConversations();
  if (workspace.currentConversationId === id) {
    workspace.currentConversationId = null;
    workspace.messages = [];
  }
}

async function loadProjectKnowledge() {
  if (!currentProject.value) return;
  projectRuntimeBusy.value = true;
  try {
    const [projectFiles, bindings] = await Promise.all([
      listProjectKnowledgeFiles(currentProject.value.id),
      listProjectGlobalKnowledgeBindings(currentProject.value.id),
    ]);
    projectKnowledgeFiles.value = projectFiles;
    projectBindings.value = bindings;
    projectBindingSelection.value = bindings.map((item) => item.id);
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '读取项目知识失败'));
  } finally {
    projectRuntimeBusy.value = false;
  }
}
async function openProjectKnowledge() {
  projectKnowledgeOpen.value = true;
  await loadProjectKnowledge();
}
async function removeProjectKnowledgeFile(file: KnowledgeFile) {
  if (!currentProject.value) return;
  await ElMessageBox.confirm(
    `删除项目知识“${file.originalName}”？`,
    '删除项目知识',
    { type: 'warning' },
  );
  try {
    await deleteProjectKnowledgeFile(currentProject.value.id, file.id);
    await loadProjectKnowledge();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '删除项目知识失败'));
  }
}
async function saveProjectBindings() {
  if (!currentProject.value) return;
  const before = new Set(projectBindings.value.map((item) => item.id));
  const after = new Set(projectBindingSelection.value);
  projectRuntimeBusy.value = true;
  try {
    for (const id of before)
      if (!after.has(id))
        await unbindProjectGlobalKnowledgeBase(currentProject.value.id, id);
    for (const id of after)
      if (!before.has(id))
        await bindProjectGlobalKnowledgeBase(currentProject.value.id, id);
    await loadProjectKnowledge();
    ElMessage.success('全局知识引用已更新');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '更新全局知识引用失败'));
  } finally {
    projectRuntimeBusy.value = false;
  }
}

function defaultProjectRuntime(projectId: number): ProjectRuntimeConfig {
  return {
    projectId,
    agentMode: 'all',
    agentIds: [],
    toolMode: 'all',
    toolIds: [],
    mcpMode: 'all',
    mcpServerIds: [],
    policy: {
      mode: 'inherit',
      scheduler: 'adaptive',
      planner: 'multi_objective',
      executionMode: 'auto',
      synthesisMode: 'auto',
      constraints: { maxLatencyMs: 8000, maxCost: 0.15, minQuality: 0.8 },
    },
    createdAt: '',
    updatedAt: '',
  };
}
async function openProjectRuntime() {
  if (!currentProject.value) return;
  projectRuntimeBusy.value = true;
  projectRuntimeOpen.value = true;
  try {
    projectRuntime.value = await getProjectRuntimeConfig(
      currentProject.value.id,
    );
  } catch {
    projectRuntime.value = defaultProjectRuntime(currentProject.value.id);
  } finally {
    projectRuntimeBusy.value = false;
  }
}
async function saveProjectRuntime() {
  if (!currentProject.value || !projectRuntime.value) return;
  projectRuntimeBusy.value = true;
  try {
    projectRuntime.value = await updateProjectRuntimeConfig(
      currentProject.value.id,
      projectRuntime.value,
    );
    ElMessage.success('项目 Runtime 策略已保存');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '保存项目 Runtime 策略失败'));
  } finally {
    projectRuntimeBusy.value = false;
  }
}
async function uploadProjectKnowledge(event: Event) {
  const target = event.target as HTMLInputElement;
  if (!currentProject.value || !target.files?.length) return;
  projectRuntimeBusy.value = true;
  try {
    for (const file of [...target.files])
      await uploadProjectKnowledgeFile(currentProject.value.id, file);
    if (projectKnowledgeOpen.value) await loadProjectKnowledge();
    ElMessage.success('项目知识已上传并进入索引流程');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '上传项目知识失败'));
  } finally {
    target.value = '';
    projectRuntimeBusy.value = false;
  }
}

function openProjectDialog(projectId: null | number = null) {
  projectEditingId.value = projectId;
  const project = resources.projects.find((item) => item.id === projectId);
  projectName.value = project?.name ?? '';
  projectDescription.value = project?.description ?? '';
  projectDialogOpen.value = true;
}

async function saveProject() {
  const name = projectName.value.trim();
  if (!name) return ElMessage.warning('请输入项目名称');
  try {
    await (projectEditingId.value === null ||
    projectEditingId.value === undefined
      ? createProject(name, projectDescription.value.trim())
      : updateProject(
          projectEditingId.value,
          name,
          projectDescription.value.trim(),
        ));
    await resources.refreshProjects();
    projectDialogOpen.value = false;
    ElMessage.success(
      projectEditingId.value === null || projectEditingId.value === undefined
        ? '项目已创建'
        : '项目已更新',
    );
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '保存项目失败'));
  }
}

async function removeProject(projectId: number) {
  const project = resources.projects.find((item) => item.id === projectId);
  await ElMessageBox.confirm(
    `删除项目“${project?.name ?? projectId}”？项目内会话不会被删除。`,
    '删除项目',
    { type: 'warning' },
  );
  try {
    await deleteProject(projectId);
    if (selectedProjectId.value === projectId) selectedProjectId.value = null;
    await Promise.all([
      resources.refreshProjects(),
      resources.refreshConversations(),
    ]);
    ElMessage.success('项目已删除');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '删除项目失败'));
  }
}

function openMoveConversation(conversationId: number) {
  moveConversationId.value = conversationId;
  const project = resources.projects.find((item) =>
    item.conversationIds.includes(conversationId),
  );
  moveProjectId.value = project?.id ?? null;
  moveDialogOpen.value = true;
}

async function saveConversationProject() {
  if (
    moveConversationId.value === null ||
    moveConversationId.value === undefined
  )
    return;
  try {
    await (moveProjectId.value === null || moveProjectId.value === undefined
      ? removeConversationFromProject(moveConversationId.value)
      : moveConversationToProject(
          moveConversationId.value,
          moveProjectId.value,
        ));
    await resources.refreshProjects();
    moveDialogOpen.value = false;
    ElMessage.success('会话归属已更新');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '移动会话失败'));
  }
}

async function loadOlder() {
  const scroller = messageScroller.value;
  if (!scroller || !workspace.hasMore) return;
  const first = scroller.querySelector<HTMLElement>('[data-message-id]');
  const beforeTop = first?.getBoundingClientRect().top ?? null;
  const beforeId = first?.dataset.messageId ?? null;
  const beforeHeight = scroller.scrollHeight;
  const beforeScroll = scroller.scrollTop;
  await workspace.loadOlderMessages();
  await nextTick();
  if (beforeId && beforeTop !== null && beforeTop !== undefined) {
    const anchor = scroller.querySelector<HTMLElement>(
      `[data-message-id="${beforeId}"]`,
    );
    if (anchor) {
      scroller.scrollTop += anchor.getBoundingClientRect().top - beforeTop;
      return;
    }
  }
  scroller.scrollTop = beforeScroll + (scroller.scrollHeight - beforeHeight);
}

async function submit() {
  if (workspace.busy) return;
  const text = draft.value;
  draft.value = '';
  try {
    const result = await workspace.submit(text);
    maybeStartDurableWatch(result);
    scrollBottom();
  } catch (error) {
    if (!workspace.error)
      ElMessage.error(friendlyApiError(error, '任务提交失败'));
    if (!draft.value.trim()) draft.value = text;
  }
}

async function resume() {
  if (!resumeText.value.trim()) return;
  try {
    const result = await workspace.resumeWaitingTask(resumeText.value);
    maybeStartDurableWatch(result);
    resumeText.value = '';
    scrollBottom();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '继续任务失败'));
  }
}

async function decide(decision: 'approve' | 'reject') {
  try {
    const result = await workspace.decideApproval(decision);
    maybeStartDurableWatch(result);
    scrollBottom();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '审批操作失败'));
  }
}

async function onFiles(event: Event) {
  const target = event.target as HTMLInputElement;
  if (!target.files?.length) return;
  try {
    await workspace.addFiles([...target.files]);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '附件上传失败');
  }
  target.value = '';
}

function openRun(result: null | RunResult = latestRun.value) {
  if (!result) return;
  workspace.openRunDetails(result);
  runDetailsOpen.value = true;
}

function formatMs(value?: null | number) {
  if (value === null || value === undefined) return '—';
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;
}

function formatCost(value?: null | number) {
  if (value === null || value === undefined) return '—';
  return `$${Number(value).toFixed(4)}`;
}

function cancelDurableWatch() {
  durableWatchToken += 1;

  durableController?.abort();
  durableController = null;

  if (durableFallback !== null && durableFallback !== undefined) {
    window.clearInterval(durableFallback);
    durableFallback = null;
  }

  durableWatchTaskId = null;
  durableWatchConversationId = null;
}

function maybeStartDurableWatch(result: null | RunResult | undefined) {
  const task = result?.task;

  if (!task || task.deliveryMode !== 'durable') {
    return;
  }

  const status = String(task.status).toUpperCase();

  if (!['QUEUED', 'RUNNING'].includes(status)) {
    return;
  }

  const conversationId = task.conversationId ?? workspace.currentConversationId;

  if (conversationId === null || conversationId === undefined) {
    return;
  }

  if (
    durableWatchTaskId === task.id &&
    durableWatchConversationId === conversationId &&
    durableController &&
    !durableController.signal.aborted
  ) {
    return;
  }

  void restartDurableWatch(task.id, conversationId);
}

function restoreDurableWatchForConversation(conversationId: null | number) {
  if (conversationId === null || conversationId === undefined) {
    cancelDurableWatch();
    return;
  }

  const task = findActiveDurableTask(conversationId);

  if (!task) {
    cancelDurableWatch();
    return;
  }

  if (
    durableWatchTaskId === task.id &&
    durableWatchConversationId === conversationId &&
    durableController &&
    !durableController.signal.aborted
  ) {
    return;
  }

  void restartDurableWatch(task.id, conversationId);
}

async function restartDurableWatch(taskId: number, conversationId: number) {
  cancelDurableWatch();

  durableWatchTaskId = taskId;
  durableWatchConversationId = conversationId;

  const token = durableWatchToken;
  const controller = new AbortController();

  durableController = controller;

  let cursor: number | string = 0;
  let streamConnected = false;
  let fallbackBusy = false;
  let finalized = false;

  const refreshAuthoritativeState = async () => {
    if (token !== durableWatchToken) return;

    await Promise.allSettled([
      resources.refreshTasks(),
      resources.refreshConversations(),
      workspace.refreshMessages(conversationId),
    ]);
  };

  const finalize = async () => {
    if (finalized || token !== durableWatchToken) {
      return;
    }

    finalized = true;

    if (durableFallback !== null && durableFallback !== undefined) {
      window.clearInterval(durableFallback);
      durableFallback = null;
    }

    if (workspace.currentConversationId === conversationId) {
      workspace.streamingAnswer = '';
      workspace.streamingPhase = '';
    }

    durableWatchTaskId = null;
    durableWatchConversationId = null;

    await refreshAuthoritativeState();
  };

  // SSE 是 Durable task 状态和实时回答的主通道。
  // 仅在 SSE 断开连接时启用 HTTP fallback。
  durableFallback = window.setInterval(() => {
    if (
      token !== durableWatchToken ||
      controller.signal.aborted ||
      streamConnected ||
      fallbackBusy
    ) {
      return;
    }

    fallbackBusy = true;

    void resources
      .refreshTasks()
      .then(async () => {
        if (token !== durableWatchToken) {
          return;
        }

        const task = resources.tasks.find((item) => item.id === taskId);

        if (!task) {
          return;
        }

        const status = String(task.status).toUpperCase();

        if (
          [
            'AUTH_REQUIRED',
            'CANCELED',
            'COMPLETED',
            'ERROR',
            'FAILED',
            'INPUT_REQUIRED',
          ].includes(status)
        ) {
          controller.abort();
          await finalize();
        }
      })
      .finally(() => {
        fallbackBusy = false;
      });
  }, 5000);

  void (async () => {
    // Token/controller state changes asynchronously in watcher callbacks.
    // oxlint-disable-next-line eslint/no-unmodified-loop-condition
    while (token === durableWatchToken && !controller.signal.aborted) {
      try {
        const next = await subscribeDurableTaskEvents(
          taskId,
          cursor,
          (event) => {
            if (
              token !== durableWatchToken ||
              workspace.currentConversationId !== conversationId
            ) {
              return;
            }

            if (event.type === 'stream_reset') {
              workspace.streamingAnswer = '';
              workspace.streamingPhase = 'Worker 已切换，正在重新连接…';
              return;
            }

            if (event.type === 'delta') {
              workspace.streamingPhase = '正在生成回答…';
              workspace.streamingAnswer += event.delta;
              return;
            }

            const phaseNames: Record<string, string> = {
              task: '\u4EFB\u52A1',
              planner: '\u89C4\u5212',
              scheduler: '\u8C03\u5EA6',
              agent: 'Agent',
              tool: '\u5DE5\u5177',
              mcp: 'MCP',
              rag: '\u77E5\u8BC6\u68C0\u7D22',
              knowledge: '\u77E5\u8BC6',
              memory: '\u8BB0\u5FC6',
              model: '\u6A21\u578B',
            };

            const phaseStatusNames: Record<string, string> = {
              running: '\u6267\u884C\u4E2D',
              completed: '\u5DF2\u5B8C\u6210',
              error: '\u5931\u8D25',
              queued: '\u6392\u961F\u4E2D',
            };

            workspace.streamingPhase =
              event.eventType === 'trace' && event.phase && event.phaseStatus
                ? `${phaseNames[event.phase] ?? '\u6267\u884C'}\uFF1A${
                    phaseStatusNames[event.phaseStatus] ?? event.phaseStatus
                  }`
                : `\u4EFB\u52A1\u72B6\u6001\uFF1A${taskStatusLabel(
                    event.status,
                  )}`;

            // SSE is the authoritative live-status channel.
            // Do not refresh tasks/conversations for every frame.
          },
          controller.signal,
          () => {
            streamConnected = true;
          },
          (nextCursor) => {
            cursor = nextCursor;
          },
        );

        cursor = next.cursor;
        streamConnected = false;

        if (next.terminal) {
          await finalize();
          break;
        }
      } catch {
        streamConnected = false;

        if (controller.signal.aborted) {
          break;
        }
      }

      if (!controller.signal.aborted) {
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
    }
  })();
}

function taskStatusLabel(status: string) {
  const map: Record<string, string> = {
    QUEUED: '排队中',
    RUNNING: '执行中',
    INPUT_REQUIRED: '等待输入',
    AUTH_REQUIRED: '等待审批',
    COMPLETED: '完成',
    ERROR: '失败',
    CANCELED: '已取消',
  };
  return map[status.toUpperCase()] ?? status;
}

watch(() => workspace.streamingAnswer, scrollBottom);

watch(
  () => workspace.currentConversationId,
  (conversationId, previousConversationId) => {
    if (conversationId === previousConversationId) {
      return;
    }

    restoreDurableWatchForConversation(conversationId);
  },
);

onBeforeUnmount(() => {
  cancelDurableWatch();
});

onMounted(async () => {
  await Promise.all([resources.refreshAll(), workspace.loadSettingsData()]);

  if (
    resources.conversations.length > 0 &&
    (workspace.currentConversationId === null ||
      workspace.currentConversationId === undefined)
  ) {
    const firstConversation = resources.conversations[0];
    if (!firstConversation) return;
    await openConversation(firstConversation.id);

    restoreDurableWatchForConversation(workspace.currentConversationId);

    return;
  }

  restoreDurableWatchForConversation(workspace.currentConversationId);
});
</script>

<template>
  <div class="workspace-page">
    <aside class="workspace-rail">
      <div class="rail-head">
        <div>
          <span class="rail-kicker">最近</span>
          <h2>任务与项目</h2>
        </div>
        <div style="display: flex; gap: 5px">
          <el-button circle title="新建项目" @click="openProjectDialog()">
            ⌂
</el-button><el-button type="primary" circle @click="createConversation()">
            ＋
          </el-button>
        </div>
      </div>
      <el-button class="new-task" type="primary" @click="createConversation()">
        ＋ 新建任务
      </el-button>

      <div class="rail-scroll">
        <div class="rail-section-title">项目</div>
        <div
          v-for="project in resources.projects"
          :key="project.id"
          class="project-wrap"
        >
          <button
            class="project-row"
            :class="{ active: selectedProjectId === project.id }"
            @click="selectedProjectId = project.id"
          >
            <span>⌄ {{ project.name }}</span><span>{{ project.conversationIds.length }}</span>
          </button>
          <el-dropdown
            class="project-menu"
            trigger="click"
            @command="
              (command: string | number | object) =>
                command === 'edit'
                  ? openProjectDialog(project.id)
                  : command === 'delete'
                    ? removeProject(project.id)
                    : undefined
            "
          >
            <button class="project-more">⋯</button><template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="edit">编辑项目</el-dropdown-item><el-dropdown-item command="delete" divided>
                  删除项目
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <div v-if="resources.projects.length === 0" class="rail-empty">
          还没有项目
        </div>

        <div class="rail-section-title recent-title">最近会话</div>
        <div
          v-for="conversation in conversationGroups.ungrouped"
          :key="conversation.id"
          class="conversation-wrap"
        >
          <button
            class="conversation-row"
            :class="{
              active:
                (workspace.currentConversationId === conversation.id &&
                  selectedProjectId === null) ||
                selectedProjectId === undefined,
            }"
            @click="openConversation(conversation.id)"
          >
            <span class="conversation-dot">●</span>
            <span class="conversation-copy"><b>{{ conversation.title }}</b><small>{{
                conversation.lastMessageAt
                  ? new Date(conversation.lastMessageAt).toLocaleString()
                  : '暂无消息'
              }}</small></span>
          </button>
          <button
            class="conversation-move"
            title="移动到项目"
            @click.stop="openMoveConversation(conversation.id)"
          >
            ↗
</button><button
            class="conversation-delete"
            title="删除"
            @click.stop="removeConversation(conversation.id)"
          >
            ×
          </button>
        </div>
        <template
          v-for="project in resources.projects"
          :key="`p-${project.id}`"
        >
          <div
            v-for="conversation in conversationGroups.projectMap.get(
              project.id,
            ) ?? []"
            :key="conversation.id"
            class="conversation-wrap"
          >
            <button
              class="conversation-row"
              :class="{
                active:
                  (workspace.currentConversationId === conversation.id &&
                    selectedProjectId === null) ||
                  selectedProjectId === undefined,
              }"
              @click="openConversation(conversation.id)"
            >
              <span class="conversation-dot">●</span>
              <span class="conversation-copy"><b>{{ conversation.title }}</b><small>{{ project.name }}</small></span>
            </button>
            <button
              class="conversation-move"
              title="移动到项目"
              @click.stop="openMoveConversation(conversation.id)"
            >
              ↗
</button><button
              class="conversation-delete"
              title="删除"
              @click.stop="removeConversation(conversation.id)"
            >
              ×
            </button>
          </div>
        </template>
      </div>
    </aside>

    <section class="workspace-center">
      <template v-if="currentProject">
        <div class="project-home">
          <div class="project-kicker">PROJECT</div>
          <h1>{{ currentProject.name }}</h1>
          <p>
            {{
              currentProject.description ||
              '项目级知识、会话和 Runtime 策略统一在这里组织。'
            }}
          </p>
          <input
            ref="projectKnowledgeInput"
            hidden
            type="file"
            multiple
            @change="uploadProjectKnowledge"
          />
          <div
            style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px"
          >
            <el-button
              type="primary"
              @click="createConversation(currentProject.id)"
            >
              ＋ 新建任务
</el-button><el-button @click="projectKnowledgeInput?.click()">
              上传项目知识
</el-button><el-button @click="openProjectKnowledge">项目知识管理</el-button><el-button @click="openProjectRuntime">Runtime 策略</el-button><el-button @click="openProjectDialog(currentProject.id)">
              编辑项目
            </el-button>
          </div>
          <div class="project-metrics">
            <div class="am-card">
              <span>会话</span><b>{{ currentProject.conversationIds.length }}</b>
            </div>
            <div class="am-card">
              <span>智能体</span><b>{{ resources.activeAgents.length }}</b>
            </div>
            <div class="am-card">
              <span>工具</span><b>{{ resources.enabledTools.length }}</b>
            </div>
          </div>
        </div>
      </template>

      <template v-else>
        <header class="conversation-head">
          <div>
            <div class="conversation-breadcrumb">
              工作台 /
              <strong>{{
                workspace.currentConversation?.title || '新任务'
              }}</strong>
            </div>
            <div class="conversation-subtitle">
              AgentMesh 负责规划、协作与执行，你只需要关注结果。
            </div>
          </div>
          <div class="head-actions">
            <el-button @click="settingsOpen = true">⚙ 运行设置</el-button>
            <el-button :disabled="!latestRun" @click="openRun()">
              运行详情 →
            </el-button>
          </div>
        </header>

        <div
          ref="messageScroller"
          class="message-scroller"
          data-testid="message-scroller"
        >
          <div v-if="workspace.hasMore" class="load-more">
            <el-button
              text
              :loading="workspace.messageLoading"
              @click="loadOlder"
            >
              加载更早消息
            </el-button>
          </div>

          <EmptyState
            v-if="visibleMessages.length === 0 && !workspace.pendingPrompt"
            title="今天想让 AgentMesh 帮你完成什么？"
            description="描述目标即可。系统会根据上下文自动决定是否需要知识、工具、Agent 或审批。"
          >
            <div class="starter-grid">
              <button @click="draft = '分析一份数据并总结关键趋势'">
                分析数据
</button><button @click="draft = '总结一份文档并提炼重点'">
                总结文档
</button><button @click="draft = '基于知识库检索并给出引用答案'">
                检索知识
</button><button @click="draft = '帮我排查一个代码问题'">排查问题</button>
            </div>
          </EmptyState>

          <article
            v-for="message in visibleMessages"
            :key="message.id"
            class="message-block"
            :class="message.role"
            :data-testid="
              message.role === 'user' ? 'message-user' : 'message-assistant'
            "
            :data-message-id="message.id"
          >
            <div v-if="message.role === 'assistant'" class="assistant-avatar">
              AM
            </div>
            <div class="message-copy">
              <div class="message-role">
                {{ message.role === 'user' ? '你' : 'AgentMesh' }}
              </div>
              <div class="message-content">{{ message.content }}</div>
              <div
                v-if="message.metadata?.attachments?.length"
                class="message-attachments"
              >
                <span
                  v-for="item in message.metadata.attachments"
                  :key="item.id"
                  >📎 {{ item.name }}</span>
              </div>
              <div
                v-if="message.metadata?.citations?.length"
                class="message-citations"
              >
                <span
                  v-for="citation in message.metadata.citations"
                  :key="citation.citationId"
                  >{{ citation.label }} {{ citation.source }}</span>
              </div>
            </div>
          </article>

          <article
            v-if="workspace.pendingPrompt"
            class="message-block user pending"
          >
            <div class="message-copy">
              <div class="message-role">你</div>
              <div class="message-content">{{ workspace.pendingPrompt }}</div>
            </div>
          </article>
          <article
            v-if="workspace.streamingAnswer || workspace.streamingPhase"
            class="message-block assistant streaming"
          >
            <div class="assistant-avatar">AM</div>
            <div class="message-copy">
              <div class="message-role">AgentMesh</div>
              <div class="streaming-phase">{{ workspace.streamingPhase }}</div>
              <div class="message-content">{{ workspace.streamingAnswer }}</div>
            </div>
          </article>

          <section
            v-if="waitingTask?.status === 'AUTH_REQUIRED'"
            class="approval-card"
            data-testid="approval-card"
          >
            <div>
              <div class="approval-kicker">高风险操作需要确认</div>
              <h3>
                {{ waitingTask.approval?.summary || '该工具操作需要你的授权' }}
              </h3>
              <p>
                {{ waitingTask.approval?.toolName }} · 风险等级
                {{ waitingTask.approval?.riskLevel }}
              </p>
            </div>
            <div class="approval-actions">
              <el-button @click="decide('reject')">拒绝</el-button><el-button type="primary" @click="decide('approve')">
                批准执行
              </el-button>
            </div>
          </section>
          <section
            v-if="waitingTask?.status === 'INPUT_REQUIRED'"
            class="approval-card"
          >
            <div>
              <div class="approval-kicker">任务等待更多输入</div>
              <h3>补充信息后继续执行</h3>
            </div>
            <div class="resume-row">
              <el-input
                v-model="resumeText"
                placeholder="补充任务所需信息…"
                @keyup.enter="resume"
              /><el-button type="primary" @click="resume">继续</el-button>
            </div>
          </section>
          <div style="height: 24px"></div>
        </div>

        <div class="composer-wrap">
          <div v-if="workspace.error" class="composer-error">
            {{ workspace.error }}
          </div>
          <div v-if="workspace.attachments.length" class="attachment-list">
            <div
              v-for="item in workspace.attachments"
              :key="item.localId"
              class="attachment-chip"
            >
              📎 {{ item.file.name }}
              <span>{{
                item.status === 'uploading'
                  ? `${item.progress}%`
                  : item.status === 'error'
                    ? '失败'
                    : '完成'
              }}</span><button @click="workspace.removeAttachment(item.localId)">
                ×
              </button>
            </div>
          </div>
          <div class="composer-card">
            <textarea
              v-model="draft"
              :disabled="workspace.busy"
              placeholder="描述目标，AgentMesh 会自动规划并执行…"
              @keydown.ctrl.enter.prevent="submit"
              @keydown.meta.enter.prevent="submit"
            ></textarea>
            <input
              ref="fileInput"
              type="file"
              multiple
              hidden
              @change="onFiles"
            />
            <div class="composer-toolbar">
              <el-button @click="fileInput?.click()">
                📎 添加图片或文件
</el-button><span class="composer-hint">支持拖拽；Ctrl / ⌘ + Enter 发送</span>
              <div class="toolbar-spacer"></div>
              <el-button @click="settingsOpen = true">自动选择⌄</el-button><el-button
                type="primary"
                :loading="workspace.busy"
                :disabled="
                  (!draft.trim() && workspace.attachments.length === 0) ||
                  !!waitingTask
                "
                @click="submit"
              >
                运行任务 →
              </el-button>
            </div>
          </div>
        </div>
      </template>
    </section>

    <aside class="workspace-run-rail">
      <div class="run-rail-head">
        <div>
          <span>运行详情</span>
          <h3>
            {{ latestRun ? taskStatusLabel(latestRun.status) : '当前工作区' }}
          </h3>
        </div>
        <span class="run-pulse"></span>
      </div>
      <div v-if="latestRun" class="run-status am-card">
        <div class="run-status-icon">✓</div>
        <div>
          <strong>{{ taskStatusLabel(latestRun.status) }}</strong><small>{{ formatMs(latestRun.elapsedMs) }}</small>
        </div>
      </div>
      <div v-else class="run-status am-card">
        <div class="run-status-icon idle">◇</div>
        <div>
          <strong>执行环境已连接</strong><small>提交任务后这里会展示真实 Trace</small>
        </div>
      </div>

      <section class="run-section">
        <div class="run-section-title">当前能力</div>
        <div class="capability-grid">
          <div>
            <span>智能体</span><b>{{ resources.activeAgents.length }}</b>
          </div>
          <div>
            <span>工具</span><b>{{ resources.tools.length }}</b>
          </div>
          <div>
            <span>MCP</span><b>{{ resources.enabledMcp.length }}</b>
          </div>
          <div>
            <span>项目</span><b>{{ resources.projects.length }}</b>
          </div>
        </div>
      </section>

      <section class="run-section">
        <div class="run-section-title">执行过程</div>
        <div v-if="traceSteps.length" class="trace-list">
          <div
            v-for="step in traceSteps"
            :key="`${step.kind}-${step.title}`"
            class="trace-row"
          >
            <span class="trace-node" :class="step.status"></span>
            <div>
              <b>{{ step.title }}</b><small>{{ step.detail }}</small>
            </div>
            <em>{{ formatMs(step.elapsedMs) }}</em>
          </div>
        </div>
        <div v-else class="trace-placeholder">
          <span>Semantic</span><span>Routing</span><span>RAG / Tool</span><span>Governance</span><small>每次任务只展示真实产生的运行事件，不用演示数据填充。</small>
        </div>
      </section>

      <section v-if="latestRun" class="run-section">
        <div class="run-section-title">执行信息</div>
        <div class="run-stat-grid">
          <div>
            <span>Token</span><b>{{ observability?.modelTotalTokens ?? 0 }}</b>
          </div>
          <div>
            <span>耗时</span><b>{{ formatMs(latestRun.elapsedMs) }}</b>
          </div>
          <div>
            <span>费用</span><b>{{ formatCost(latestRun.estimatedCost) }}</b>
          </div>
        </div>
        <div class="selected-agents" v-if="latestRun.selectedAgents?.length">
          <span>使用的智能体</span><b>{{ latestRun.selectedAgents.join(' · ') }}</b>
        </div>
        <el-button style="width: 100%; margin-top: 10px" @click="openRun()">
          查看完整 Run Details
        </el-button>
      </section>

      <section class="run-section">
        <div class="run-section-title">可用智能体</div>
        <div class="agent-mini-list">
          <div
            v-for="agent in resources.activeAgents.slice(0, 6)"
            :key="agent.id"
          >
            <span class="mini-avatar">{{
              agent.name.slice(0, 2).toUpperCase()
            }}</span><b>{{ agent.name }}</b><span class="online-dot"></span>
          </div>
        </div>
      </section>
    </aside>
  </div>

  <el-dialog
    v-model="projectDialogOpen"
    :title="
      projectEditingId === null || projectEditingId === undefined
        ? '新建项目'
        : '编辑项目'
    "
    width="500px"
  >
    <el-form label-position="top">
      <el-form-item label="项目名称">
        <el-input v-model="projectName" />
</el-form-item><el-form-item label="描述">
        <el-input v-model="projectDescription" type="textarea" :rows="3" />
      </el-form-item>
</el-form><template #footer>
      <el-button @click="projectDialogOpen = false">取消</el-button><el-button type="primary" @click="saveProject">保存</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="moveDialogOpen" title="移动会话到项目" width="460px">
    <el-select
      v-model="moveProjectId"
      clearable
      placeholder="不属于任何项目"
      style="width: 100%"
    >
      <el-option
        v-for="project in resources.projects"
        :key="project.id"
        :label="project.name"
        :value="project.id"
      />
</el-select><template #footer>
      <el-button @click="moveDialogOpen = false">取消</el-button><el-button type="primary" @click="saveConversationProject">
        确认
      </el-button>
    </template>
  </el-dialog>
  <el-drawer v-model="projectKnowledgeOpen" title="项目知识管理" size="620px">
    <template v-if="currentProject">
      <div v-loading="projectRuntimeBusy">
        <div class="detail-event">
          <div class="event-head">
            <b>项目知识文件</b><el-button
              size="small"
              type="primary"
              @click="projectKnowledgeInput?.click()"
            >
              上传
            </el-button>
          </div>
          <el-table :data="projectKnowledgeFiles" size="small">
            <el-table-column
              prop="originalName"
              label="文件"
              min-width="220"
            /><el-table-column
              prop="status"
              label="状态"
              width="100"
            /><el-table-column
              prop="chunkCount"
              label="Chunks"
              width="90"
            /><el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button
                  link
                  type="danger"
                  @click="removeProjectKnowledgeFile(row)"
                >
                  删除
                </el-button>
              </template>
            </el-table-column>
</el-table><EmptyState
            v-if="!projectKnowledgeFiles.length"
            title="还没有项目知识文件"
          />
        </div>
        <div class="detail-event" style="margin-top: 12px">
          <div class="event-head">
            <b>引用全局知识库</b><span class="am-muted">显式绑定后当前项目才可使用</span>
          </div>
          <el-select
            v-model="projectBindingSelection"
            multiple
            clearable
            placeholder="选择允许引用的全局知识库"
            style="width: 100%"
          >
            <el-option
              v-for="base in workspace.knowledgeBases.filter(
                (item) => item.scope === 'GLOBAL',
              )"
              :key="base.id"
              :label="base.name"
              :value="base.id"
            />
</el-select><el-button
            type="primary"
            style="width: 100%; margin-top: 10px"
            @click="saveProjectBindings"
          >
            保存引用范围
          </el-button>
        </div>
      </div>
    </template>
  </el-drawer>

  <el-drawer
    v-model="projectRuntimeOpen"
    title="项目 Runtime 策略"
    size="500px"
  >
    <template v-if="projectRuntime">
      <el-form label-position="top" v-loading="projectRuntimeBusy">
        <el-form-item label="Agent 范围">
          <el-radio-group v-model="projectRuntime.agentMode">
            <el-radio-button label="all">全部</el-radio-button><el-radio-button label="selected">
              指定
            </el-radio-button>
</el-radio-group><el-select
            v-if="projectRuntime.agentMode === 'selected'"
            v-model="projectRuntime.agentIds"
            multiple
            style="width: 100%; margin-top: 8px"
          >
            <el-option
              v-for="agent in resources.agents"
              :key="agent.id"
              :label="agent.name"
              :value="agent.id"
            />
          </el-select>
</el-form-item><el-form-item label="Tool 范围">
          <el-radio-group v-model="projectRuntime.toolMode">
            <el-radio-button label="all">全部</el-radio-button><el-radio-button label="selected">
              指定
            </el-radio-button>
</el-radio-group><el-select
            v-if="projectRuntime.toolMode === 'selected'"
            v-model="projectRuntime.toolIds"
            multiple
            style="width: 100%; margin-top: 8px"
          >
            <el-option
              v-for="tool in resources.tools"
              :key="tool.id"
              :label="tool.name"
              :value="tool.id"
            />
          </el-select>
</el-form-item><el-form-item label="MCP 范围">
          <el-radio-group v-model="projectRuntime.mcpMode">
            <el-radio-button label="all">全部</el-radio-button><el-radio-button label="selected">
              指定
            </el-radio-button>
</el-radio-group><el-select
            v-if="projectRuntime.mcpMode === 'selected'"
            v-model="projectRuntime.mcpServerIds"
            multiple
            style="width: 100%; margin-top: 8px"
          >
            <el-option
              v-for="server in resources.mcpServers"
              :key="server.id"
              :label="server.name"
              :value="server.id"
            />
          </el-select>
</el-form-item><el-divider>运行策略</el-divider><el-form-item label="策略来源">
          <el-radio-group v-model="projectRuntime.policy.mode">
            <el-radio-button label="inherit">继承默认</el-radio-button><el-radio-button label="project"> 项目自定义 </el-radio-button>
          </el-radio-group>
</el-form-item><template v-if="projectRuntime.policy.mode === 'project'">
          <el-form-item label="Scheduler">
            <el-select
              v-model="projectRuntime.policy.scheduler"
              style="width: 100%"
            >
              <el-option label="Adaptive" value="adaptive" /><el-option
                label="Capability"
                value="capability"
              /><el-option label="Greedy" value="greedy" /><el-option
                label="Fixed"
                value="fixed"
              />
            </el-select>
</el-form-item><el-form-item label="Planner">
            <el-select
              v-model="projectRuntime.policy.planner"
              style="width: 100%"
            >
              <el-option
                label="Multi Objective"
                value="multi_objective"
              /><el-option label="Heuristic" value="heuristic" />
            </el-select>
</el-form-item><el-form-item label="执行模式">
            <el-select
              v-model="projectRuntime.policy.executionMode"
              style="width: 100%"
            >
              <el-option label="Auto" value="auto" /><el-option
                label="Parallel"
                value="parallel"
              /><el-option label="Sequential" value="sequential" />
            </el-select>
</el-form-item><el-form-item label="Synthesis">
            <el-select
              v-model="projectRuntime.policy.synthesisMode"
              style="width: 100%"
            >
              <el-option label="Auto" value="auto" /><el-option
                label="Always"
                value="always"
              /><el-option label="Never" value="never" />
            </el-select>
</el-form-item><el-form-item label="最大延迟">
            <el-input-number
              v-model="projectRuntime.policy.constraints.maxLatencyMs"
              :min="1000"
              :step="1000"
              style="width: 100%"
            />
</el-form-item><el-form-item label="最大成本">
            <el-input-number
              v-model="projectRuntime.policy.constraints.maxCost"
              :min="0"
              :step="0.05"
              :precision="2"
              style="width: 100%"
            />
</el-form-item><el-form-item label="最低质量">
            <el-slider
              v-model="projectRuntime.policy.constraints.minQuality"
              :min="0"
              :max="1"
              :step="0.05"
            />
          </el-form-item>
</template><el-button
          type="primary"
          style="width: 100%"
          :loading="projectRuntimeBusy"
          @click="saveProjectRuntime"
        >
          保存项目策略
        </el-button>
      </el-form>
    </template>
  </el-drawer>

  <el-drawer v-model="settingsOpen" title="运行设置" size="430px">
    <el-form label-position="top">
      <el-form-item label="Scheduler">
        <el-select v-model="workspace.scheduler" style="width: 100%">
          <el-option label="Adaptive" value="adaptive" /><el-option
            label="Capability"
            value="capability"
          /><el-option label="Greedy" value="greedy" /><el-option
            label="Fixed"
            value="fixed"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="Planner">
        <el-select v-model="workspace.planner" style="width: 100%">
          <el-option
            label="Multi Objective"
            value="multi_objective"
          /><el-option label="Heuristic" value="heuristic" />
        </el-select>
      </el-form-item>
      <el-form-item label="执行模式">
        <el-select v-model="workspace.executionMode" style="width: 100%">
          <el-option label="Auto" value="auto" /><el-option
            label="Parallel"
            value="parallel"
          /><el-option label="Sequential" value="sequential" />
        </el-select>
      </el-form-item>
      <el-form-item label="Delivery">
        <el-select v-model="workspace.deliveryMode" style="width: 100%">
          <el-option label="Auto" value="auto" /><el-option
            label="Direct"
            value="direct"
          /><el-option label="Durable" value="durable" />
        </el-select>
      </el-form-item>
      <el-form-item label="RAG">
        <el-select v-model="workspace.ragMode" style="width: 100%">
          <el-option label="AUTO" value="AUTO" /><el-option
            label="ON"
            value="ON"
          /><el-option label="OFF" value="OFF" />
        </el-select>
      </el-form-item>
      <el-form-item label="知识库">
        <el-select
          v-model="workspace.selectedKnowledgeBaseIds"
          multiple
          clearable
          style="width: 100%"
        >
          <el-option
            v-for="base in workspace.knowledgeBases"
            :key="base.id"
            :label="base.name"
            :value="base.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="模型">
        <el-select
          v-model="workspace.modelSelection.serviceId"
          clearable
          style="width: 100%"
          @change="
            workspace.modelSelection.mode = workspace.modelSelection.serviceId
              ? 'manual'
              : 'auto'
          "
        >
          <el-option label="自动选择" :value="null" /><el-option
            v-for="service in workspace.modelServices"
            :key="service.id"
            :label="`${service.name} · ${service.modelName}`"
            :value="service.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="最大延迟 (ms)">
        <el-input-number
          v-model="workspace.latency"
          :min="1000"
          :step="1000"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="最大成本">
        <el-input-number
          v-model="workspace.cost"
          :min="0"
          :step="0.1"
          :precision="2"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="最低质量">
        <el-slider v-model="workspace.quality" :min="0" :max="1" :step="0.05" />
      </el-form-item>
      <el-checkbox v-model="workspace.retryOnWorkerLoss">
        Worker 丢失时允许恢复
      </el-checkbox>
    </el-form>
  </el-drawer>

  <el-drawer
    v-model="runDetailsOpen"
    title="Run Details"
    size="560px"
    @closed="workspace.closeRunDetails()"
  >
    <template v-if="workspace.detailsRun">
      <div class="detail-summary">
        <StatusBadge :status="workspace.detailsRun.status" /><strong>Task #{{ workspace.detailsRun.task.id }}</strong><span>{{ formatMs(workspace.detailsRun.elapsedMs) }}</span><span>{{ formatCost(workspace.detailsRun.estimatedCost) }}</span>
      </div>
      <el-tabs>
        <el-tab-pane label="Trace">
          <el-timeline>
            <el-timeline-item
              v-for="step in workspace.detailsRun.trace"
              :key="`${step.kind}-${step.title}`"
              :timestamp="formatMs(step.elapsedMs)"
              :type="
                step.status === 'completed'
                  ? 'success'
                  : step.status === 'error'
                    ? 'danger'
                    : 'primary'
              "
            >
              <strong>{{ step.title }}</strong>
              <div class="am-muted">{{ step.kind }} · {{ step.status }}</div>
            </el-timeline-item>
          </el-timeline>
        </el-tab-pane>
        <el-tab-pane label="DAG">
          <div class="dag-view">
            <div
              v-for="node in workspace.detailsRun.dag?.nodes ?? []"
              :key="node.id"
              class="dag-node"
            >
              <span>{{ node.kind }}</span><b>{{ node.label }}</b><StatusBadge :status="node.status" />
            </div>
          </div>
        </el-tab-pane>
        <el-tab-pane :label="`Routing (${routingEvents.length})`">
          <div v-if="routingEvents.length" class="detail-event-list">
            <article
              v-for="event in routingEvents"
              :key="`${event.kind}-${event.elapsedMs}`"
              class="detail-event"
            >
              <div class="event-head">
                <b>{{ event.title }}</b><StatusBadge :status="event.status" />
              </div>
              <el-descriptions :column="2" size="small" border>
                <el-descriptions-item label="Selected">
                  {{
                    safeRoutingSummary(event.detail).selected
                  }}
</el-descriptions-item><el-descriptions-item label="Score">
                  {{
                    safeRoutingSummary(event.detail).score
                  }}
</el-descriptions-item><el-descriptions-item label="Mode">
                  {{
                    safeRoutingSummary(event.detail).mode
                  }}
</el-descriptions-item><el-descriptions-item label="Degraded">
                  {{ safeRoutingSummary(event.detail).degraded ? '是' : '否' }}
                </el-descriptions-item>
              </el-descriptions>
              <p
                v-if="safeRoutingSummary(event.detail).reason"
                class="detail-note"
              >
                {{ safeRoutingSummary(event.detail).reason }}
              </p>
            </article>
          </div>
          <EmptyState
            v-else
            title="没有路由事件"
            description="固定路由或快速路径可能不会产生自适应路由记录。"
          />
        </el-tab-pane>
        <el-tab-pane :label="`Discovery (${discoveryEvents.length})`">
          <div v-if="discoveryEvents.length" class="detail-event-list">
            <article
              v-for="event in discoveryEvents"
              :key="`${event.kind}-${event.elapsedMs}`"
              class="detail-event"
            >
              <div class="event-head">
                <b>{{ event.title }}</b><StatusBadge :status="event.status" />
              </div>
              <div class="detail-chips">
                <span
                  v-for="name in discoverySummary(event.detail).tools"
                  :key="`t-${name}`"
                  >Tool · {{ name }}</span><span
                  v-for="name in discoverySummary(event.detail).mcp"
                  :key="`m-${name}`"
                  >MCP · {{ name }}</span><span
                  v-for="name in discoverySummary(event.detail).skills"
                  :key="`s-${name}`"
                  >Skill · {{ name }}</span><span v-if="discoverySummary(event.detail).knowledge">Knowledge · selected</span>
              </div>
            </article>
          </div>
          <EmptyState
            v-else
            title="没有能力发现事件"
            description="普通快速对话不会进入能力发现。"
          />
        </el-tab-pane>
        <el-tab-pane :label="`RAG (${ragEvents.length})`">
          <div class="detail-event-list">
            <article
              v-for="event in ragEvents"
              :key="`${event.kind}-${event.elapsedMs}`"
              class="detail-event"
            >
              <div class="event-head">
                <b>{{ event.title }}</b><StatusBadge :status="event.status" />
              </div>
              <div class="detail-note">
                {{ event.kind }} · {{ formatMs(event.elapsedMs) }}
              </div>
            </article>
          </div>
          <el-descriptions
            :column="2"
            size="small"
            border
            style="margin-top: 10px"
          >
            <el-descriptions-item label="Retrieval Mode">
              {{
                workspace.detailsRun.observability?.retrievalMode || '—'
              }}
</el-descriptions-item><el-descriptions-item label="RAG Hits">
              {{
                workspace.detailsRun.observability?.ragHits ?? 0
              }}
</el-descriptions-item><el-descriptions-item label="Raw Hits">
              {{
                workspace.detailsRun.observability?.ragRawHits ?? 0
              }}
</el-descriptions-item><el-descriptions-item label="Latency">
              {{ formatMs(workspace.detailsRun.observability?.ragLatencyMs) }}
            </el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane :label="`Tool & MCP (${toolEvents.length})`">
          <div class="detail-event-list">
            <article
              v-for="event in toolEvents"
              :key="`${event.kind}-${event.elapsedMs}`"
              class="detail-event"
            >
              <div class="event-head">
                <b>{{ event.title }}</b><StatusBadge :status="event.status" />
              </div>
              <div class="detail-note">
                {{ event.kind === 'approval' ? 'human approval' : event.kind }}
                ·
                {{
                  formatMs(event.elapsedMs)
                }}。为避免泄漏，这里不展开工具参数和返回正文。
              </div>
            </article>
          </div>
          <el-descriptions
            :column="2"
            size="small"
            border
            style="margin-top: 10px"
          >
            <el-descriptions-item label="Tool Calls">
              {{
                workspace.detailsRun.observability?.toolCalls ?? 0
              }}
</el-descriptions-item><el-descriptions-item label="MCP Events">
              {{
                workspace.detailsRun.observability?.mcpEvents ?? 0
              }}
</el-descriptions-item><el-descriptions-item label="Tool Success">
              {{
                workspace.detailsRun.observability?.toolSuccesses ?? 0
              }}
</el-descriptions-item><el-descriptions-item label="Tool Failure">
              {{ workspace.detailsRun.observability?.toolFailures ?? 0 }}
            </el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane :label="`Memory (${memoryEvents.length})`">
          <div class="detail-event-list">
            <article
              v-for="event in memoryEvents"
              :key="`${event.kind}-${event.elapsedMs}`"
              class="detail-event"
            >
              <div class="event-head">
                <b>{{
                  event.kind === 'memory_retrieval'
                    ? 'Memory 召回'
                    : event.kind === 'memory_write'
                      ? 'Memory 写入'
                      : 'Memory 忘记'
                }}</b><StatusBadge :status="event.status" />
              </div>
              <div class="detail-note">
                {{ event.title }} ·
                {{
                  formatMs(event.elapsedMs)
                }}。这里只展示决策元数据，不展示完整记忆内容。
              </div>
            </article>
          </div>
          <EmptyState
            v-if="!memoryEvents.length"
            title="本次运行没有 Memory 事件"
            description="可能是 Memory 未参与本次执行，或属于特殊 Resume 路径。"
          />
        </el-tab-pane>
        <el-tab-pane :label="`Reliability (${reliabilityEvents.length})`">
          <div class="detail-event-list">
            <article
              v-for="event in reliabilityEvents"
              :key="`${event.kind}-${event.elapsedMs}`"
              class="detail-event"
            >
              <div class="event-head">
                <b>{{ event.title }}</b><StatusBadge :status="event.status" />
              </div>
              <div class="detail-note">{{ formatMs(event.elapsedMs) }}</div>
            </article>
          </div>
        </el-tab-pane>
        <el-tab-pane
          :label="`Citations (${workspace.detailsRun.citations.length})`"
        >
          <div class="detail-event-list">
            <article
              v-for="citation in workspace.detailsRun.citations"
              :key="citation.citationId"
              class="detail-event"
            >
              <div class="event-head">
                <b>{{ citation.label }} · {{ citation.source }}</b><span>{{ citation.score.toFixed(3) }}</span>
              </div>
              <div class="detail-note">
                {{ citation.documentType || 'document' }} · chunk
                {{ citation.chunkIndex ?? '—' }} · page
                {{ citation.pageNumber ?? '—' }} ·
                {{ citation.modality || 'text' }}
              </div>
            </article>
          </div>
          <EmptyState
            v-if="!workspace.detailsRun.citations.length"
            title="本次回答没有引用"
          />
        </el-tab-pane>
        <el-tab-pane label="Eval">
          <template v-if="workspace.detailsRun.scorecard">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="Overall">
                {{
                  workspace.detailsRun.scorecard.overallScore
                }}
</el-descriptions-item><el-descriptions-item label="Status">
                {{
                  workspace.detailsRun.scorecard.status
                }}
</el-descriptions-item><el-descriptions-item label="Groundedness">
                {{
                  workspace.detailsRun.scorecard.groundedness
                }}
</el-descriptions-item><el-descriptions-item label="Tool Reliability">
                {{
                  workspace.detailsRun.scorecard.toolReliability
                }}
</el-descriptions-item><el-descriptions-item label="RAG Quality">
                {{
                  workspace.detailsRun.scorecard.ragQuality
                }}
</el-descriptions-item><el-descriptions-item label="Memory Contribution">
                {{
                  workspace.detailsRun.scorecard.memoryContribution
                }}
</el-descriptions-item><el-descriptions-item label="Budget Compliance">
                {{
                  workspace.detailsRun.scorecard.budgetCompliance
                }}
</el-descriptions-item><el-descriptions-item label="Model Tokens">
                {{ workspace.detailsRun.scorecard.modelTokens }}
              </el-descriptions-item>
            </el-descriptions>
            <p class="detail-note">
              {{ workspace.detailsRun.scorecard.judgeReason }}
            </p>
</template><EmptyState v-else title="本次运行没有 Eval Scorecard" />
        </el-tab-pane>
        <el-tab-pane label="Observability">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="Model">
              {{
                workspace.detailsRun.observability?.modelName || '—'
              }}
</el-descriptions-item><el-descriptions-item label="Provider">
              {{
                workspace.detailsRun.observability?.modelProvider || '—'
              }}
</el-descriptions-item><el-descriptions-item label="Token">
              {{
                workspace.detailsRun.observability?.modelTotalTokens ?? 0
              }}
</el-descriptions-item><el-descriptions-item label="Tool Calls">
              {{
                workspace.detailsRun.observability?.toolCalls ?? 0
              }}
</el-descriptions-item><el-descriptions-item label="RAG Hits">
              {{
                workspace.detailsRun.observability?.ragHits ?? 0
              }}
</el-descriptions-item><el-descriptions-item label="Cost">
              {{
                formatCost(workspace.detailsRun.estimatedCost)
              }}
</el-descriptions-item><el-descriptions-item label="Agent Attempts">
              {{
                workspace.detailsRun.observability?.agentAttempts ?? 0
              }}
</el-descriptions-item><el-descriptions-item label="Reschedules">
              {{ workspace.detailsRun.observability?.reschedules ?? 0 }}
            </el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
      </el-tabs>
    </template>
  </el-drawer>
</template>

<style scoped>
.workspace-page {
  display: grid;
  grid-template-columns: 230px minmax(0, 1fr) 285px;
  height: calc(100vh - 62px);
  height: calc(100dvh - 62px);
  min-height: 0;
  overflow: hidden;
  background: var(--am-surface-2);
}

.workspace-rail {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: 18px 12px;
  background: #fff;
  border-right: 1px solid var(--am-border);
}

.rail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px 12px;
}

.rail-head h2 {
  margin: 2px 0 0;
  font-size: 17px;
}

.rail-kicker,
.rail-section-title {
  font-size: 10px;
  font-weight: 800;
  color: var(--am-muted);
}

.new-task {
  width: 100%;
  height: 40px;
  font-weight: 800;
  box-shadow: 0 10px 22px rgb(108 76 255 / 18%);
}

.rail-scroll {
  margin-top: 16px;
  overflow: auto;
}

.rail-section-title {
  padding: 10px 8px 6px;
}

.recent-title {
  margin-top: 10px;
}

.project-wrap {
  position: relative;
}

.project-row {
  display: flex;
  justify-content: space-between;
  width: 100%;
  padding: 8px;
  font-size: 12px;
  color: #596176;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 9px;
}

.project-row:hover,
.project-row.active {
  color: var(--am-primary);
  background: #f7f5ff;
}

.project-menu {
  position: absolute;
  top: 4px;
  right: 4px;
}

.project-more {
  width: 24px;
  height: 24px;
  color: var(--am-muted);
  cursor: pointer;
  background: transparent;
  border: 0;
}

.project-wrap:not(:hover) .project-menu {
  opacity: 0;
}

.rail-empty {
  padding: 7px 8px;
  font-size: 11px;
  color: var(--am-muted);
}

.conversation-wrap {
  position: relative;
}

.conversation-row {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr);
  gap: 7px;
  width: 100%;
  padding: 9px 24px 9px 8px;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 10px;
}

.conversation-row:hover,
.conversation-row.active {
  background: var(--am-primary-soft);
}

.conversation-dot {
  margin-top: 4px;
  font-size: 8px;
  color: #95a0b1;
}

.conversation-row.active .conversation-dot {
  color: var(--am-primary);
}

.conversation-copy {
  min-width: 0;
}

.conversation-copy b,
.conversation-copy small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-copy b {
  font-size: 11px;
}

.conversation-copy small {
  margin-top: 3px;
  font-size: 9px;
  color: var(--am-muted);
}

.conversation-move,
.conversation-delete {
  position: absolute;
  top: 8px;
  display: none;
  width: 22px;
  height: 22px;
  cursor: pointer;
  background: #fff;
  border: 0;
  border-radius: 7px;
}

.conversation-move {
  right: 29px;
  color: var(--am-primary);
}

.conversation-delete {
  right: 5px;
  color: var(--am-danger);
}

.conversation-wrap:hover .conversation-delete,
.conversation-wrap:hover .conversation-move {
  display: block;
}

.workspace-center {
  display: grid;
  grid-template-rows: 72px minmax(0, 1fr) auto;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: #fbfbfe;
}

.conversation-head {
  display: flex;
  gap: 14px;
  align-items: center;
  justify-content: space-between;
  height: 72px;
  padding: 0 24px;
  background: #fff;
  border-bottom: 1px solid var(--am-border);
}

.conversation-breadcrumb {
  font-size: 13px;
  color: #7d8496;
}

.conversation-breadcrumb strong {
  font-size: 15px;
  color: var(--am-text);
}

.conversation-subtitle {
  margin-top: 5px;
  font-size: 10px;
  color: var(--am-muted);
}

.head-actions {
  display: flex;
  gap: 8px;
}

.message-scroller {
  min-height: 0;
  padding: 18px max(22px, 6vw) 24px;
  overflow: auto;
  scroll-behavior: auto;
}

.load-more {
  margin-bottom: 12px;
  text-align: center;
}

.message-block {
  display: flex;
  gap: 10px;
  margin: 16px 0;
}

.message-block.user {
  justify-content: flex-end;
}

.message-block.user .message-copy {
  max-width: 72%;
  padding: 12px 14px;
  background: var(--am-primary-soft);
  border-radius: 16px 16px 5px;
}

.message-block.assistant .message-copy {
  flex: 1;
  max-width: 850px;
}

.assistant-avatar {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 34px;
  height: 34px;
  font-size: 10px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #6c4cff, #8f62ff);
  border-radius: 10px;
  box-shadow: 0 8px 18px rgb(108 76 255 / 20%);
}

.message-role {
  margin-bottom: 5px;
  font-size: 10px;
  font-weight: 800;
  color: #788093;
}

.message-content {
  font-size: 13px;
  line-height: 1.9;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.message-attachments,
.message-citations {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.message-attachments span,
.message-citations span {
  padding: 5px 8px;
  font-size: 9px;
  color: #737b8e;
  background: #fff;
  border: 1px solid var(--am-border);
  border-radius: 8px;
}

.streaming-phase {
  margin-bottom: 5px;
  font-size: 11px;
  color: var(--am-primary);
}

.approval-card {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  margin: 14px 0;
  background: #fff;
  border: 1px solid #ddd5ff;
  border-radius: 14px;
  box-shadow: var(--am-shadow);
}

.approval-card h3 {
  margin: 4px 0;
  font-size: 15px;
}

.approval-card p {
  margin: 0;
  font-size: 11px;
  color: var(--am-muted);
}

.approval-kicker {
  font-size: 10px;
  font-weight: 800;
  color: var(--am-primary);
}

.approval-actions,
.resume-row {
  display: flex;
  gap: 8px;
}

.resume-row {
  min-width: 360px;
}

.starter-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 16px;
}

.starter-grid button {
  padding: 11px;
  color: #5e6577;
  cursor: pointer;
  background: #fff;
  border: 1px solid var(--am-border);
  border-radius: 10px;
}

.starter-grid button:hover {
  color: var(--am-primary);
  border-color: #cfc6ff;
}

.composer-wrap {
  position: relative;
  right: auto;
  bottom: auto;
  left: auto;
  z-index: 5;
  padding: 8px max(18px, 5vw) 16px;
  background: linear-gradient(180deg, rgb(251 251 254 / 0%), #fbfbfe 18%);
}

.composer-card {
  overflow: hidden;
  background: #fff;
  border: 1px solid var(--am-border-strong);
  border-radius: 16px;
  box-shadow: 0 20px 45px rgb(42 37 85 / 12%);
}

.composer-card textarea {
  width: 100%;
  height: 86px;
  padding: 15px 16px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--am-text);
  resize: none;
  outline: 0;
  background: #fff;
  border: 0;
}

.composer-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 9px 11px;
  background: #fdfdff;
  border-top: 1px solid var(--am-border);
}

.composer-hint {
  font-size: 9px;
  color: var(--am-muted);
}

.toolbar-spacer {
  flex: 1;
}

.composer-error {
  padding: 8px 10px;
  margin-bottom: 7px;
  font-size: 11px;
  color: var(--am-danger);
  background: #fff5f6;
  border: 1px solid #f4cfd3;
  border-radius: 10px;
}

.attachment-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 7px;
}

.attachment-chip {
  display: flex;
  gap: 5px;
  align-items: center;
  padding: 6px 8px;
  font-size: 10px;
  background: #fff;
  border: 1px solid var(--am-border);
  border-radius: 9px;
}

.attachment-chip span {
  color: var(--am-muted);
}

.attachment-chip button {
  color: var(--am-danger);
  cursor: pointer;
  background: transparent;
  border: 0;
}

.workspace-run-rail {
  min-width: 0;
  min-height: 0;
  padding: 16px;
  overflow: auto;
  background: #fff;
  border-left: 1px solid var(--am-border);
}

.run-rail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
}

.run-rail-head span:first-child {
  font-size: 9px;
  color: var(--am-muted);
}

.run-rail-head h3 {
  margin: 3px 0 0;
  font-size: 16px;
}

.run-pulse {
  width: 9px;
  height: 9px;
  background: var(--am-primary);
  border-radius: 50%;
  box-shadow: 0 0 0 5px var(--am-primary-soft);
}

.run-status {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 12px;
  box-shadow: none;
}

.run-status-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  font-weight: 900;
  color: #fff;
  background: var(--am-primary);
  border-radius: 50%;
}

.run-status-icon.idle {
  color: var(--am-primary);
  background: var(--am-primary-soft);
}

.run-status strong,
.run-status small {
  display: block;
}

.run-status strong {
  font-size: 11px;
}

.run-status small {
  margin-top: 3px;
  font-size: 9px;
  color: var(--am-muted);
}

.run-section {
  padding: 15px 0;
  border-bottom: 1px solid var(--am-border);
}

.run-section-title {
  margin-bottom: 9px;
  font-size: 10px;
  font-weight: 800;
  color: #6c7386;
}

.capability-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}

.capability-grid div,
.run-stat-grid div {
  padding: 10px;
  background: #f8f7fd;
  border: 1px solid #eeecf8;
  border-radius: 10px;
}

.capability-grid span,
.run-stat-grid span {
  display: block;
  font-size: 8px;
  color: var(--am-muted);
}

.capability-grid b,
.run-stat-grid b {
  display: block;
  margin-top: 3px;
  font-size: 15px;
}

.trace-list {
  display: grid;
  gap: 2px;
}

.trace-row {
  position: relative;
  display: grid;
  grid-template-columns: 15px minmax(0, 1fr) auto;
  gap: 7px;
  padding: 8px 0;
}

.trace-row:not(:last-child)::after {
  position: absolute;
  top: 24px;
  bottom: -6px;
  left: 6px;
  width: 1px;
  content: '';
  background: #dcd5ff;
}

.trace-node {
  width: 13px;
  height: 13px;
  margin-top: 2px;
  background: #c9c3df;
  border: 3px solid #f2f0fb;
  border-radius: 50%;
}

.trace-node.completed {
  background: var(--am-primary);
}

.trace-node.error {
  background: var(--am-danger);
}

.trace-row b,
.trace-row small {
  display: block;
}

.trace-row b {
  font-size: 10px;
}

.trace-row small {
  margin-top: 2px;
  font-size: 8px;
  color: var(--am-muted);
}

.trace-row em {
  font-size: 8px;
  font-style: normal;
  color: var(--am-muted);
}

.trace-placeholder {
  display: grid;
  gap: 7px;
}

.trace-placeholder span {
  padding: 7px 9px;
  font-size: 9px;
  font-weight: 800;
  color: #61568d;
  background: #f8f6ff;
  border-radius: 8px;
}

.trace-placeholder small {
  font-size: 8px;
  line-height: 1.5;
  color: var(--am-muted);
}

.run-stat-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 5px;
}

.selected-agents {
  display: flex;
  gap: 8px;
  justify-content: space-between;
  margin-top: 10px;
  font-size: 9px;
}

.selected-agents span {
  color: var(--am-muted);
}

.selected-agents b {
  text-align: right;
}

.agent-mini-list {
  display: grid;
  gap: 5px;
}

.agent-mini-list > div {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 8px;
  gap: 7px;
  align-items: center;
  padding: 7px;
  background: #faf9ff;
  border-radius: 9px;
}

.mini-avatar {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  font-size: 8px;
  font-weight: 800;
  color: var(--am-primary);
  background: var(--am-primary-soft);
  border-radius: 8px;
}

.agent-mini-list b {
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 9px;
}

.online-dot {
  width: 7px;
  height: 7px;
  background: var(--am-success);
  border-radius: 50%;
}

.project-home {
  padding: 44px;
}

.project-kicker {
  font-size: 10px;
  font-weight: 800;
  color: var(--am-primary);
}

.project-home h1 {
  margin: 6px 0;
  font-size: 36px;
}

.project-home p {
  color: var(--am-muted);
}

.project-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 24px;
}

.project-metrics > div {
  padding: 18px;
}

.project-metrics span,
.project-metrics b {
  display: block;
}

.project-metrics span {
  font-size: 11px;
  color: var(--am-muted);
}

.project-metrics b {
  margin-top: 6px;
  font-size: 26px;
}

.detail-summary {
  display: flex;
  gap: 9px;
  align-items: center;
  margin-bottom: 14px;
}

.detail-summary span:last-child {
  margin-left: auto;
}

.dag-view {
  display: grid;
  gap: 8px;
}

.dag-node {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 10px;
  border: 1px solid var(--am-border);
  border-radius: 10px;
}

.dag-node > span {
  font-size: 10px;
  font-weight: 800;
  color: var(--am-primary);
}

.raw-json {
  padding: 12px;
  margin: 0;
  overflow: auto;
  font-size: 10px;
  line-height: 1.6;
  color: #e7e4ff;
  background: #171822;
  border-radius: 10px;
}

.detail-event-list {
  display: grid;
  gap: 10px;
}

.detail-event {
  padding: 12px;
  background: #fff;
  border: 1px solid var(--am-border);
  border-radius: 11px;
}

.event-head {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.detail-note {
  margin: 8px 0 0;
  font-size: 10px;
  line-height: 1.65;
  color: var(--am-muted);
}

.detail-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.detail-chips span {
  padding: 5px 7px;
  font-size: 9px;
  font-weight: 800;
  color: var(--am-primary);
  background: var(--am-primary-soft);
  border-radius: 999px;
}

@media (max-width: 1250px) {
  .workspace-page {
    grid-template-columns: 210px minmax(0, 1fr);
  }

  .workspace-run-rail {
    display: none;
  }
}

@media (max-width: 850px) {
  .workspace-page {
    grid-template-columns: 1fr;
  }

  .workspace-rail {
    display: none;
  }

  .message-scroller {
    padding-inline: 16px;
  }

  .composer-wrap {
    padding-right: 12px;
    padding-left: 12px;
  }

  .starter-grid {
    grid-template-columns: 1fr;
  }

  .approval-card {
    flex-direction: column;
    align-items: stretch;
  }

  .resume-row {
    min-width: 0;
  }

  .conversation-head {
    padding-inline: 14px;
  }
}
</style>
