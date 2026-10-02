<script setup lang="ts">
import type {
  RuntimeReliabilitySnapshot,
  RuntimeTopologySnapshot,
  Task,
} from '#/api/agentmesh';

import { computed, onMounted, ref } from 'vue';

import { ElMessage, ElMessageBox } from 'element-plus';

import {
  cancelTask,
  deleteTask,
  friendlyApiError,
  getRuntimeReliability,
  getRuntimeTopology,
} from '#/api/agentmesh';
import MetricCard from '#/components/agentmesh/MetricCard.vue';
import PageHeader from '#/components/agentmesh/PageHeader.vue';
import StatusBadge from '#/components/agentmesh/StatusBadge.vue';
import { useAgentMeshResourcesStore } from '#/store/agentmesh-resources';

const resources = useAgentMeshResourcesStore();
const reliability = ref<null | RuntimeReliabilitySnapshot>(null);
const topology = ref<null | RuntimeTopologySnapshot>(null);
const filter = ref('ALL');
const search = ref('');
const details = ref<null | Task>(null);
const detailsOpen = ref(false);

const running = computed(
  () =>
    resources.tasks.filter((task) =>
      ['QUEUED', 'RUNNING'].includes(String(task.status).toUpperCase()),
    ).length,
);
const terminal = computed(
  () =>
    resources.tasks.filter((task) =>
      ['CANCELED', 'COMPLETED', 'ERROR'].includes(
        String(task.status).toUpperCase(),
      ),
    ).length,
);
const visible = computed(() => {
  const keyword = search.value.trim().toLowerCase();
  return resources.tasks.filter((task) => {
    const status = String(task.status).toUpperCase();
    const statusOk = filter.value === 'ALL' || status === filter.value;
    const queryOk =
      !keyword ||
      [
        task.taskText,
        task.requestId,
        String(task.id),
        ...(task.selectedAgents ?? []),
      ]
        .join(' ')
        .toLowerCase()
        .includes(keyword);
    return statusOk && queryOk;
  });
});

async function reload() {
  await resources.refreshTasks();
  const settled = await Promise.allSettled([
    getRuntimeReliability(),
    getRuntimeTopology(),
  ]);
  if (settled[0]?.status === 'fulfilled') reliability.value = settled[0].value;
  if (settled[1]?.status === 'fulfilled') topology.value = settled[1].value;
}
async function cancel(task: Task) {
  try {
    await cancelTask(task.id);
    await reload();
    ElMessage.success('已请求取消任务');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '取消失败'));
  }
}
async function remove(task: Task) {
  await ElMessageBox.confirm('删除后该任务记录不可恢复。', '删除任务', {
    type: 'warning',
  });
  try {
    await deleteTask(task.id);
    await reload();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '删除失败'));
  }
}
function inspect(task: Task) {
  details.value = task;
  detailsOpen.value = true;
}
function ms(value?: null | number) {
  if (value === null || value === undefined) return '—';
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;
}
function money(value?: null | number) {
  return value === null || value === undefined
    ? '—'
    : `$${Number(value).toFixed(4)}`;
}
function canDelete(task: Task) {
  return ['CANCELED', 'COMPLETED', 'ERROR'].includes(
    String(task.status).toUpperCase(),
  );
}

onMounted(reload);
</script>

<template>
  <div class="am-page tasks-page">
    <PageHeader
      eyebrow="EXECUTION HISTORY"
      title="任务记录"
      description="回顾最近任务、执行状态、耗时、调度策略与分布式 Runtime 状态。"
    >
      <el-button @click="reload">刷新</el-button><span class="runtime-pill" :class="{ good: reliability?.enabled }">● {{ reliability?.enabled ? '可靠执行已启用' : '执行服务' }}</span>
    </PageHeader>
    <div class="am-metrics">
      <MetricCard label="全部任务" :value="resources.tasks.length" />
      <MetricCard label="正在处理" :value="running" tone="primary" />
      <MetricCard label="可清理记录" :value="terminal" />
      <MetricCard
        label="可用 Worker"
        :value="reliability?.availableWorkers ?? 0"
        :hint="`队列 ${reliability?.queueDepth ?? 0}`"
        tone="success"
      />
    </div>

    <section class="am-card runtime-card">
      <div>
        <div class="runtime-kicker">分布式运行时</div>
        <h3>多节点执行拓扑</h3>
        <p>查看节点、Worker、队列、租约和调度容量。内部端点与凭据不会展示。</p>
      </div>
      <div class="runtime-stats">
        <div>
          <span>节点</span><b>{{ topology?.nodes.length ?? reliability?.nodes ?? 0 }}</b>
        </div>
        <div>
          <span>Worker</span><b>{{ topology?.workers.length ?? reliability?.workers ?? 0 }}</b>
        </div>
        <div>
          <span>容量</span><b>{{ reliability?.totalCapacity ?? 0 }}</b>
        </div>
        <div>
          <span>利用率</span><b>{{ reliability?.utilizationPercent ?? 0 }}%</b>
        </div>
      </div>
    </section>

    <section class="am-card task-list-card">
      <div class="task-filter">
        <el-input
          v-model="search"
          clearable
          placeholder="搜索任务、Request ID 或 Agent…"
        /><el-select v-model="filter" style="width: 160px">
          <el-option label="全部状态" value="ALL" /><el-option
            label="运行中"
            value="RUNNING"
          /><el-option label="排队中" value="QUEUED" /><el-option
            label="等待审批"
            value="AUTH_REQUIRED"
          /><el-option label="等待输入" value="INPUT_REQUIRED" /><el-option
            label="已完成"
            value="COMPLETED"
          /><el-option label="失败" value="ERROR" />
        </el-select>
      </div>
      <div class="task-list">
        <article
          v-for="task in visible"
          :key="task.id"
          class="task-row"
          @click="inspect(task)"
        >
          <div class="task-main">
            <div class="task-title">
              <b>{{ task.taskText || `任务 #${task.id}` }}</b><StatusBadge :status="String(task.status)" />
            </div>
            <div class="task-meta">
              任务 #{{ task.id }} · {{ ms(task.latencyMs) }} ·
              {{ money(task.estimatedCost) }} · {{ task.scheduler }} /
              {{ task.executionMode || 'auto' }}
            </div>
          </div>
          <div class="task-agents">
            {{ task.selectedAgents?.slice(0, 3).join(' · ') || '—' }}
          </div>
          <div class="task-actions">
            <el-button
              v-if="
                ['RUNNING', 'QUEUED'].includes(
                  String(task.status).toUpperCase(),
                )
              "
              @click.stop="cancel(task)"
            >
              取消
</el-button><el-button @click.stop="inspect(task)">查看详情</el-button><el-button
              v-if="canDelete(task)"
              type="danger"
              plain
              @click.stop="remove(task)"
            >
              删除
            </el-button>
          </div>
        </article>
      </div>
    </section>
  </div>

  <el-drawer v-model="detailsOpen" title="任务详情" size="560px">
    <template v-if="details">
      <div class="detail-summary">
        <StatusBadge :status="String(details.status)" /><b>Task #{{ details.id }}</b><span>{{ details.requestId }}</span>
      </div>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="Scheduler">
          {{ details.scheduler }}
</el-descriptions-item><el-descriptions-item label="Planner">
          {{ details.planner || '—' }}
</el-descriptions-item><el-descriptions-item label="执行模式">
          {{ details.executionMode || '—' }}
</el-descriptions-item><el-descriptions-item label="Delivery">
          {{ details.deliveryMode || '—' }}
</el-descriptions-item><el-descriptions-item label="耗时">
          {{ ms(details.latencyMs) }}
</el-descriptions-item><el-descriptions-item label="成本">
          {{ money(details.estimatedCost) }}
        </el-descriptions-item>
      </el-descriptions>
      <div class="drawer-block">
        <b>任务内容</b>
        <p>{{ details.taskText }}</p>
      </div>
      <div v-if="details.errorMessage" class="drawer-block error-block">
        <b>错误信息</b>
        <p>{{ details.errorMessage }}</p>
      </div>
      <div v-if="details.resultText" class="drawer-block">
        <b>结果</b>
        <p>{{ details.resultText }}</p>
      </div>
      <div v-if="details.trace?.length" class="drawer-block">
        <b>Trace</b><el-timeline style="margin-top: 12px">
          <el-timeline-item
            v-for="step in details.trace"
            :key="`${step.kind}-${step.title}`"
            :timestamp="ms(step.elapsedMs)"
            :type="
              step.status === 'completed'
                ? 'success'
                : step.status === 'error'
                  ? 'danger'
                  : 'primary'
            "
          >
            <strong>{{ step.title }}</strong>
            <div class="am-muted">{{ step.detail }}</div>
          </el-timeline-item>
        </el-timeline>
      </div>
      <div v-if="details.approval" class="drawer-block">
        <b>Approval</b>
        <p>{{ details.approval.summary }}</p>
        <el-tag type="warning">{{ details.approval.riskLevel }}</el-tag>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.runtime-pill {
  display: inline-flex;
  align-items: center;
  padding: 8px 10px;
  font-size: 11px;
  color: var(--am-muted);
  background: #fff;
  border: 1px solid var(--am-border);
  border-radius: 10px;
}

.runtime-pill.good {
  color: var(--am-success);
}

.runtime-card {
  display: flex;
  gap: 20px;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px;
  margin-top: 16px;
}

.runtime-kicker {
  font-size: 9px;
  font-weight: 800;
  color: var(--am-primary);
}

.runtime-card h3 {
  margin: 4px 0 3px;
}

.runtime-card p {
  margin: 0;
  font-size: 10px;
  color: var(--am-muted);
}

.runtime-stats {
  display: grid;
  grid-template-columns: repeat(4, 80px);
  gap: 8px;
}

.runtime-stats > div {
  padding: 9px;
  text-align: center;
  background: #faf9ff;
  border-radius: 10px;
}

.runtime-stats span,
.runtime-stats b {
  display: block;
}

.runtime-stats span {
  font-size: 8px;
  color: var(--am-muted);
}

.runtime-stats b {
  margin-top: 3px;
  font-size: 16px;
}

.task-list-card {
  padding: 14px;
  margin-top: 16px;
}

.task-filter {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.task-list {
  display: grid;
  gap: 8px;
}

.task-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 190px auto;
  gap: 12px;
  align-items: center;
  padding: 13px;
  cursor: pointer;
  border: 1px solid var(--am-border);
  border-radius: 12px;
  transition: 0.15s;
}

.task-row:hover {
  background: #fdfcff;
  border-color: #d8d0ff;
}

.task-title {
  display: flex;
  gap: 8px;
  align-items: center;
}

.task-title b {
  font-size: 12px;
}

.task-meta {
  margin-top: 5px;
  font-size: 9px;
  color: var(--am-muted);
}

.task-agents {
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 9px;
  color: #697085;
  white-space: nowrap;
}

.task-actions {
  display: flex;
  gap: 6px;
}

.detail-summary {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 14px;
}

.detail-summary span:last-child {
  margin-left: auto;
  font-size: 9px;
  color: var(--am-muted);
}

.drawer-block {
  margin-top: 20px;
}

.drawer-block > b {
  display: block;
  margin-bottom: 8px;
}

.drawer-block p {
  font-size: 11px;
  line-height: 1.7;
  color: #5e6578;
  white-space: pre-wrap;
}

@media (max-width: 950px) {
  .runtime-card {
    flex-direction: column;
    align-items: flex-start;
  }

  .runtime-stats {
    grid-template-columns: repeat(4, minmax(70px, 1fr));
    width: 100%;
  }

  .task-row {
    grid-template-columns: 1fr;
  }

  .task-actions {
    justify-content: flex-end;
  }
}

@media (max-width: 620px) {
  .task-filter {
    flex-direction: column;
  }

  .task-filter :deep(.el-select) {
    width: 100% !important;
  }

  .runtime-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}

.error-block {
  padding: 12px;
  background: #fff7f8;
  border: 1px solid #ffd5da;
  border-radius: 10px;
}

.error-block > b,
.error-block p {
  color: var(--am-danger);
}
</style>
