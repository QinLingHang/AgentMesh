import type {
  Conversation,
  ConversationAttachment,
  KnowledgeBase,
  Message,
  MessageAttachmentMetadata,
  ModelSelection,
  RagMode,
  RagScope,
  RunResult,
  Task,
} from '#/api/agentmesh';

import { computed, ref } from 'vue';

import { defineStore } from 'pinia';

import {
  ApiError,
  createConversation,
  decideTaskApproval,
  deleteConversationAttachment,
  friendlyApiError,
  listKnowledgeBases,
  listMessagePage,
  listUserModelServices,
  renameConversation,
  resumeTask,
  runTask,
  runTaskStream,
  uploadConversationAttachment,
} from '#/api/agentmesh';

import { useAgentMeshResourcesStore } from './agentmesh-resources';

const UNTITLED = new Set(['AgentMesh 新任务', '新任务', '新会话', '新对话']);
const WAITING = new Set(['AUTH_REQUIRED', 'INPUT_REQUIRED']);

function titleFromPrompt(prompt: string) {
  const normalized = prompt.replaceAll(/\s+/g, ' ').trim();
  const chars = [...normalized];
  if (chars.length <= 28) return normalized || '新会话';
  return `${chars.slice(0, 28).join('')}…`;
}

export type ComposerAttachment = {
  localId: string;
  file: File;
  progress: number;
  status: 'error' | 'ready' | 'uploading';
  server?: ConversationAttachment;
  error?: string;
};

export const useAgentMeshWorkspaceStore = defineStore(
  'agentmesh-workspace',
  () => {
    const resources = useAgentMeshResourcesStore();
    const currentConversationId = ref<null | number>(null);
    const messages = ref<Message[]>([]);
    const hasMore = ref(false);
    const nextBeforeId = ref<null | number>(null);
    const messageLoading = ref(false);
    const busy = ref(false);
    const error = ref('');
    const pendingPrompt = ref('');
    const pendingAttachments = ref<MessageAttachmentMetadata[]>([]);
    const streamingAnswer = ref('');
    const streamingPhase = ref('');
    const latestRun = ref<null | RunResult>(null);
    const detailsRun = ref<null | RunResult>(null);
    const attachments = ref<ComposerAttachment[]>([]);
    const knowledgeBases = ref<KnowledgeBase[]>([]);
    const modelServices = ref<
      Awaited<ReturnType<typeof listUserModelServices>>
    >([]);

    const scheduler = ref<'adaptive' | 'capability' | 'fixed' | 'greedy'>(
      'adaptive',
    );
    const planner = ref<'heuristic' | 'multi_objective'>('multi_objective');
    const executionMode = ref<'auto' | 'parallel' | 'sequential'>('auto');
    const synthesisMode = ref<'always' | 'auto' | 'never'>('auto');
    const deliveryMode = ref<'auto' | 'direct' | 'durable'>('auto');
    const ragMode = ref<RagMode>('AUTO');
    const ragScopes = ref<RagScope[]>(['PROJECT']);
    const selectedKnowledgeBaseIds = ref<number[]>([]);
    const modelSelection = ref<ModelSelection>({ mode: 'auto' });
    const latency = ref(120_000);
    const cost = ref(1);
    const quality = ref(0.7);
    const retryOnWorkerLoss = ref(true);

    let loadEpoch = 0;
    const submissionEpoch = new Map<number, number>();

    const currentConversation = computed<Conversation | null>(
      () =>
        resources.conversations.find(
          (item) => item.id === currentConversationId.value,
        ) ?? null,
    );

    const waitingTask = computed<null | Task>(() => {
      const conversationId = currentConversationId.value;
      if (conversationId === null || conversationId === undefined) return null;
      return (
        resources.tasks.find(
          (task) =>
            task.conversationId === conversationId &&
            WAITING.has(String(task.status).toUpperCase()),
        ) ?? null
      );
    });

    const activeLatestRun = computed(() => {
      if (
        !latestRun.value ||
        currentConversationId.value === null ||
        currentConversationId.value === undefined
      )
        return null;
      return latestRun.value.task.conversationId === currentConversationId.value
        ? latestRun.value
        : null;
    });

    async function loadSettingsData() {
      const settled = await Promise.allSettled([
        listKnowledgeBases(),
        listUserModelServices(),
      ]);
      if (settled[0]?.status === 'fulfilled')
        knowledgeBases.value = settled[0].value;
      if (settled[1]?.status === 'fulfilled')
        modelServices.value = settled[1].value;
    }

    async function openConversation(id: number) {
      const epoch = ++loadEpoch;
      currentConversationId.value = id;
      messageLoading.value = true;
      error.value = '';
      pendingPrompt.value = '';
      pendingAttachments.value = [];
      streamingAnswer.value = '';
      streamingPhase.value = '';
      detailsRun.value = null;
      try {
        const page = await listMessagePage(id, { limit: 100 });
        if (epoch !== loadEpoch || currentConversationId.value !== id) return;
        messages.value = page.items;
        hasMore.value = page.hasMore;
        nextBeforeId.value = page.nextBeforeId;
      } catch (caughtError) {
        if (epoch === loadEpoch)
          error.value = friendlyApiError(caughtError, '会话加载失败。');
      } finally {
        if (epoch === loadEpoch) messageLoading.value = false;
      }
    }

    async function loadOlderMessages() {
      const id = currentConversationId.value;
      if (
        id === null ||
        id === undefined ||
        !hasMore.value ||
        nextBeforeId.value === null ||
        nextBeforeId.value === undefined ||
        messageLoading.value
      )
        return;
      messageLoading.value = true;
      try {
        const page = await listMessagePage(id, {
          beforeId: nextBeforeId.value,
          limit: 100,
        });
        const byId = new Map<number, Message>();
        [...page.items, ...messages.value].forEach((item) =>
          byId.set(item.id, item),
        );
        messages.value = [...byId.values()].toSorted((a, b) => a.id - b.id);
        hasMore.value = page.hasMore;
        nextBeforeId.value = page.nextBeforeId;
      } finally {
        messageLoading.value = false;
      }
    }

    async function newConversation() {
      const created = await createConversation('新会话');
      await resources.refreshConversations();
      await openConversation(created.id);
      return created;
    }

    async function ensureConversation() {
      if (currentConversation.value) return currentConversation.value;
      return newConversation();
    }

    async function refreshMessages(id = currentConversationId.value) {
      if (id === null || id === undefined) return;
      const page = await listMessagePage(id, { limit: 100 });
      if (currentConversationId.value !== id) return;
      messages.value = page.items;
      hasMore.value = page.hasMore;
      nextBeforeId.value = page.nextBeforeId;
    }

    async function addFiles(files: File[]) {
      const allowed = new Set([
        'csv',
        'docx',
        'jpeg',
        'jpg',
        'json',
        'markdown',
        'md',
        'pdf',
        'png',
        'txt',
        'webp',
      ]);
      const available = Math.max(
        0,
        6 - attachments.value.filter((item) => item.status !== 'error').length,
      );
      const selected = files.slice(0, available);
      if (selected.length === 0) throw new Error('每次任务最多添加 6 个附件。');
      const conversation = await ensureConversation();

      for (const file of selected) {
        const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
        if (!allowed.has(extension)) throw new Error(`不支持 ${file.name}。`);
        if (file.size <= 0 || file.size > 10 * 1024 * 1024)
          throw new Error(`${file.name} 超过 10 MB 限制或为空文件。`);
        const localId =
          globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
        const draft: ComposerAttachment = {
          localId,
          file,
          progress: 0,
          status: 'uploading',
        };
        attachments.value.push(draft);
        try {
          const server = await uploadConversationAttachment(
            conversation.id,
            file,
            (progress) => {
              const item = attachments.value.find(
                (candidate) => candidate.localId === localId,
              );
              if (item) item.progress = progress;
            },
          );
          Object.assign(draft, { progress: 100, status: 'ready', server });
        } catch (error) {
          Object.assign(draft, {
            status: 'error',
            error: friendlyApiError(error, '上传失败'),
          });
        }
      }
    }

    async function removeAttachment(localId: string) {
      const index = attachments.value.findIndex(
        (item) => item.localId === localId,
      );
      if (index === -1) return;
      const item = attachments.value[index];
      if (!item) return;
      attachments.value.splice(index, 1);
      if (item.server) {
        try {
          await deleteConversationAttachment(
            item.server.conversationId,
            item.server.id,
          );
        } catch {
          /* best effort */
        }
      }
    }

    async function submit(rawText: string) {
      const ready = attachments.value.flatMap((item) =>
        item.status === 'ready' && item.server
          ? [{ ...item, server: item.server }]
          : [],
      );
      if (attachments.value.some((item) => item.status === 'uploading'))
        throw new Error('附件仍在上传，请稍候。');
      if (!rawText.trim() && ready.length === 0) return null;
      if (waitingTask.value)
        throw new Error('当前会话存在等待继续的任务，请先完成该任务。');

      const prompt = rawText.trim() || '请分析我附加的内容，并给出清晰的结论。';
      const conversation = await ensureConversation();
      const conversationId = conversation.id;
      const epoch = (submissionEpoch.get(conversationId) ?? 0) + 1;
      submissionEpoch.set(conversationId, epoch);
      const isOwner = () =>
        currentConversationId.value === conversationId &&
        submissionEpoch.get(conversationId) === epoch;

      pendingPrompt.value = prompt;
      pendingAttachments.value = ready.map((item) => ({
        id: item.server.id,
        name: item.server.originalName,
        mediaType: item.server.mediaType,
        extension: item.server.extension,
        sizeBytes: item.server.sizeBytes,
      }));
      streamingAnswer.value = '';
      streamingPhase.value = '正在连接模型…';
      busy.value = true;
      error.value = '';

      const input = {
        conversationId,
        task: prompt,
        scheduler: scheduler.value,
        planner: planner.value,
        executionMode: executionMode.value,
        synthesisMode: synthesisMode.value,
        deliveryMode: deliveryMode.value,
        ragPolicy: {
          mode: ragMode.value,
          scopes: ragScopes.value,
          selectedKnowledgeBaseIds: selectedKnowledgeBaseIds.value.filter(
            (id) => knowledgeBases.value.some((item) => item.id === id),
          ),
        },
        modelSelection: modelSelection.value,
        maxLatencyMs: latency.value,
        maxCost: cost.value,
        minQuality: quality.value,
        retryOnWorkerLoss:
          deliveryMode.value === 'direct' ? false : retryOnWorkerLoss.value,
        attachmentIds: ready.map((item) => item.server.id),
      };

      try {
        const result =
          deliveryMode.value === 'durable'
            ? await runTask(input)
            : await runTaskStream(input, {
                onDelta: (delta) => {
                  if (!isOwner()) return;
                  streamingPhase.value = '正在生成回答…';
                  streamingAnswer.value += delta;
                },
                onStatus: (message) => {
                  if (isOwner()) streamingPhase.value = message;
                },
              });

        if (isOwner()) latestRun.value = result;
        if (UNTITLED.has(conversation.title)) {
          try {
            await renameConversation(conversationId, titleFromPrompt(prompt));
          } catch {
            /* non-fatal */
          }
        }
        await Promise.allSettled([
          resources.refreshTasks(),
          resources.refreshConversations(),
        ]);
        if (currentConversationId.value === conversationId)
          await refreshMessages(conversationId);
        attachments.value = [];
        return result;
      } catch (caughtError) {
        const acceptedStreamFailure =
          caughtError instanceof ApiError && caughtError.code === 50_210;
        if (acceptedStreamFailure) {
          await Promise.allSettled([
            resources.refreshTasks(),
            resources.refreshConversations(),
            refreshMessages(conversationId),
          ]);
        }
        if (isOwner())
          error.value = friendlyApiError(
            caughtError,
            '任务提交失败，请稍后重试。',
          );
        throw caughtError;
      } finally {
        if (isOwner()) {
          pendingPrompt.value = '';
          pendingAttachments.value = [];
          streamingAnswer.value = '';
          streamingPhase.value = '';
        }
        busy.value = false;
      }
    }

    async function resumeWaitingTask(text: string) {
      const task = waitingTask.value;
      const conversationId = currentConversationId.value;
      if (
        !task ||
        conversationId === null ||
        conversationId === undefined ||
        !text.trim()
      )
        return null;
      const result = await resumeTask(task.id, text.trim());
      latestRun.value = result;
      await Promise.all([
        refreshMessages(conversationId),
        resources.refreshTasks(),
        resources.refreshConversations(),
      ]);
      return result;
    }

    async function decideApproval(decision: 'approve' | 'reject') {
      const task = waitingTask.value;
      const conversationId = currentConversationId.value;
      if (!task || conversationId === null || conversationId === undefined)
        return null;
      if (
        task.conversationId !== null &&
        task.conversationId !== undefined &&
        task.conversationId !== conversationId
      )
        throw new Error('该审批已不属于当前会话。');
      const result = await decideTaskApproval(task.id, decision);
      if (currentConversationId.value === conversationId)
        latestRun.value = result;
      await Promise.all([
        refreshMessages(conversationId),
        resources.refreshTasks(),
        resources.refreshConversations(),
      ]);
      return result;
    }

    function openRunDetails(result: null | RunResult = activeLatestRun.value) {
      detailsRun.value = result;
    }
    function closeRunDetails() {
      detailsRun.value = null;
    }

    return {
      currentConversationId,
      currentConversation,
      messages,
      hasMore,
      nextBeforeId,
      messageLoading,
      busy,
      error,
      pendingPrompt,
      pendingAttachments,
      streamingAnswer,
      streamingPhase,
      latestRun,
      activeLatestRun,
      detailsRun,
      attachments,
      knowledgeBases,
      modelServices,
      waitingTask,
      scheduler,
      planner,
      executionMode,
      synthesisMode,
      deliveryMode,
      ragMode,
      ragScopes,
      selectedKnowledgeBaseIds,
      modelSelection,
      latency,
      cost,
      quality,
      retryOnWorkerLoss,
      loadSettingsData,
      openConversation,
      loadOlderMessages,
      newConversation,
      refreshMessages,
      addFiles,
      removeAttachment,
      submit,
      resumeWaitingTask,
      decideApproval,
      openRunDetails,
      closeRunDetails,
    };
  },
);
