<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';

import { ElMessage } from 'element-plus';

import { createAgent, friendlyApiError, seedDemoAgents } from '#/api/agentmesh';
import MetricCard from '#/components/agentmesh/MetricCard.vue';
import PageHeader from '#/components/agentmesh/PageHeader.vue';
import StatusBadge from '#/components/agentmesh/StatusBadge.vue';
import { useAgentMeshResourcesStore } from '#/store/agentmesh-resources';

const resources = useAgentMeshResourcesStore();
const query = ref('');
const drawerOpen = ref(false);
const createOpen = ref(false);
const selectedId = ref<null | number>(null);
const form = reactive({
  name: '自定义智能体',
  endpoint: 'http://127.0.0.1:9999/agent',
  protocol: 'http',
  capabilities: 'general',
  provider: 'external',
});

const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase();
  if (!keyword) return resources.agents;
  return resources.agents.filter((agent) =>
    [agent.name, agent.description, agent.protocol, ...agent.capabilities]
      .join(' ')
      .toLowerCase()
      .includes(keyword),
  );
});
const selected = computed(
  () => resources.agents.find((agent) => agent.id === selectedId.value) ?? null,
);
const successAverage = computed(() =>
  resources.agents.length > 0
    ? (
        (resources.agents.reduce((sum, item) => sum + item.successRate, 0) /
          resources.agents.length) *
        100
      ).toFixed(1)
    : '0.0',
);
const latencyAverage = computed(() =>
  resources.agents.length > 0
    ? Math.round(
        resources.agents.reduce((sum, item) => sum + item.avgLatencyMs, 0) /
          resources.agents.length,
      )
    : 0,
);

async function seed() {
  try {
    await seedDemoAgents();
    await resources.refreshAgents();
    ElMessage.success('演示智能体已创建');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '创建失败'));
  }
}
async function create() {
  try {
    await createAgent({
      name: form.name.trim(),
      description: `${form.name} Agent`,
      endpoint: form.endpoint.trim(),
      protocol: form.protocol,
      capabilities: form.capabilities
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean),
      provider: form.provider,
      qualityScore: 0.8,
      avgLatencyMs: 1000,
      avgCost: 0.01,
      successRate: 0.95,
      failureRate: 0,
      currentLoad: 0,
    });
    createOpen.value = false;
    await resources.refreshAgents();
    ElMessage.success('智能体已添加');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '添加失败'));
  }
}
function inspect(id: number) {
  selectedId.value = id;
  drawerOpen.value = true;
}
function percent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}
function latency(value: number) {
  return value >= 1000
    ? `${(value / 1000).toFixed(1)}s`
    : `${Math.round(value)}ms`;
}

onMounted(() => resources.refreshAgents());
</script>

<template>
  <div class="am-page agents-page">
    <PageHeader
      eyebrow="AI TEAM"
      title="智能体"
      description="查看、接入和管理参与任务协作的 AI 成员；运行指标来自真实 Agent 注册信息。"
    >
      <el-button @click="seed">创建演示智能体</el-button><el-button type="primary" @click="createOpen = true">
        ＋ 添加智能体
      </el-button>
    </PageHeader>

    <div class="am-metrics agents-metrics">
      <MetricCard label="全部智能体" :value="resources.agents.length" />
      <MetricCard
        label="当前可用"
        :value="resources.activeAgents.length"
        tone="success"
      />
      <MetricCard label="平均成功率" :value="`${successAverage}%`" />
      <MetricCard label="平均延迟" :value="latency(latencyAverage)" />
    </div>

    <div class="agents-layout">
      <section>
        <div class="am-card search-card">
          <el-input
            v-model="query"
            clearable
            placeholder="搜索智能体、协议或能力…"
          />
        </div>
        <div class="agent-grid">
          <article
            v-for="agent in filtered"
            :key="agent.id"
            class="am-card agent-card"
            @click="inspect(agent.id)"
          >
            <div class="agent-card-head">
              <div class="agent-avatar">
                {{ agent.name.slice(0, 2).toUpperCase() }}
              </div>
              <StatusBadge :status="agent.status" />
            </div>
            <h3>{{ agent.name }}</h3>
            <p>{{ agent.description || '平台智能体' }}</p>
            <div class="cap-list">
              <el-tag
                v-for="capability in agent.capabilities.slice(0, 4)"
                :key="capability"
                round
                effect="light"
              >
                {{ capability }}
              </el-tag>
            </div>
            <div class="agent-stats">
              <div>
                <span>质量</span><b>{{ Math.round(agent.qualityScore) }}</b>
              </div>
              <div>
                <span>成功率</span><b>{{ percent(agent.successRate) }}</b>
              </div>
              <div>
                <span>平均耗时</span><b>{{ latency(agent.avgLatencyMs) }}</b>
              </div>
              <div>
                <span>当前负载</span><b>{{ agent.currentLoad }}</b>
              </div>
            </div>
            <div class="agent-card-foot">
              <span>{{ agent.protocol }} · {{ agent.provider }}</span><span>查看详情 →</span>
            </div>
          </article>
        </div>
      </section>

      <aside class="agents-side">
        <div class="am-card side-card">
          <div class="side-title">
            <span>已启用智能体</span><b>{{ resources.activeAgents.length }}/{{
                resources.agents.length
              }}</b>
          </div>
          <div class="enabled-list">
            <button
              v-for="agent in resources.activeAgents"
              :key="agent.id"
              @click="inspect(agent.id)"
            >
              <span class="small-avatar">{{
                agent.name.slice(0, 2).toUpperCase()
              }}</span><span><b>{{ agent.name }}</b><small>{{
                  agent.capabilities.slice(0, 2).join(' · ') || 'general'
                }}</small></span><i></i>
            </button>
          </div>
        </div>
        <div class="am-card side-card">
          <div class="side-title"><span>协作编排</span><b>默认执行链</b></div>
          <div class="chain">
            <div
              v-for="(agent, index) in resources.activeAgents.slice(0, 4)"
              :key="agent.id"
            >
              <span>{{ index + 1 }}</span>
              <div>
                <b>{{ agent.name }}</b><small>{{
                  index === 0
                    ? '意图理解与规划'
                    : index === 1
                      ? '检索 / 工具'
                      : index === 2
                        ? '执行任务'
                        : '结果检查'
                }}</small>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>

  <el-dialog v-model="createOpen" title="添加智能体" width="540px">
    <el-form label-position="top">
      <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
      <el-form-item label="Endpoint">
        <el-input v-model="form.endpoint" />
      </el-form-item>
      <el-form-item label="协议">
        <el-select v-model="form.protocol" style="width: 100%">
          <el-option label="HTTP" value="http" /><el-option
            label="A2A"
            value="a2a"
          /><el-option label="Internal" value="internal" />
        </el-select>
      </el-form-item>
      <el-form-item label="能力（逗号分隔）">
        <el-input v-model="form.capabilities" />
      </el-form-item>
      <el-form-item label="Provider">
        <el-input v-model="form.provider" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="createOpen = false">取消</el-button><el-button type="primary" @click="create">添加</el-button>
    </template>
  </el-dialog>

  <el-drawer v-model="drawerOpen" title="智能体详情" size="480px">
    <template v-if="selected">
      <div class="detail-head">
        <div class="agent-avatar large">
          {{ selected.name.slice(0, 2).toUpperCase() }}
        </div>
        <div>
          <h2>{{ selected.name }}</h2>
          <StatusBadge :status="selected.status" />
        </div>
      </div>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="描述">
          {{ selected.description }}
</el-descriptions-item><el-descriptions-item label="协议">
          {{ selected.protocol }}
</el-descriptions-item><el-descriptions-item label="Provider">
          {{ selected.provider }}
</el-descriptions-item><el-descriptions-item label="模型">
          {{ selected.modelName || '—' }}
</el-descriptions-item><el-descriptions-item label="Endpoint">
          {{ selected.endpoint }}
</el-descriptions-item><el-descriptions-item label="成功率">
          {{ percent(selected.successRate) }}
</el-descriptions-item><el-descriptions-item label="平均延迟">
          {{ latency(selected.avgLatencyMs) }}
        </el-descriptions-item>
      </el-descriptions>
      <div class="drawer-section">
        <b>能力</b>
        <div class="cap-list">
          <el-tag v-for="capability in selected.capabilities" :key="capability">
            {{ capability }}
          </el-tag>
        </div>
      </div>
      <div v-if="selected.capabilityProfiles?.length" class="drawer-section">
        <b>Capability Profiles</b><el-table :data="selected.capabilityProfiles" size="small">
          <el-table-column prop="capability" label="能力" /><el-table-column
            prop="qualityScore"
            label="质量"
          /><el-table-column prop="sampleCount" label="样本" />
        </el-table>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.agents-metrics {
  margin-bottom: 16px;
}

.agents-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 290px;
  gap: 16px;
}

.search-card {
  padding: 10px;
  margin-bottom: 12px;
  box-shadow: none;
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.agent-card {
  padding: 16px;
  cursor: pointer;
  transition: 0.18s ease;
}

.agent-card:hover {
  border-color: #d9d1ff;
  box-shadow: 0 18px 34px rgb(71 57 135 / 10%);
  transform: translateY(-2px);
}

.agent-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.agent-avatar {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  font-size: 11px;
  font-weight: 850;
  color: var(--am-primary);
  background: var(--am-primary-soft);
  border-radius: 12px;
}

.agent-avatar.large {
  width: 52px;
  height: 52px;
  font-size: 14px;
}

.agent-card h3 {
  margin: 14px 0 4px;
  font-size: 16px;
}

.agent-card p {
  min-height: 34px;
  margin: 0;
  font-size: 11px;
  line-height: 1.55;
  color: var(--am-muted);
}

.cap-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 10px;
}

.agent-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 14px;
  overflow: hidden;
  border: 1px solid var(--am-border);
  border-radius: 10px;
}

.agent-stats > div {
  padding: 9px;
  border-right: 1px solid var(--am-border);
  border-bottom: 1px solid var(--am-border);
}

.agent-stats > div:nth-child(2n) {
  border-right: 0;
}

.agent-stats > div:nth-child(n + 3) {
  border-bottom: 0;
}

.agent-stats span,
.agent-stats b {
  display: block;
}

.agent-stats span {
  font-size: 9px;
  color: var(--am-muted);
}

.agent-stats b {
  margin-top: 3px;
  font-size: 12px;
}

.agent-card-foot {
  display: flex;
  gap: 8px;
  justify-content: space-between;
  margin-top: 11px;
  font-size: 9px;
  color: var(--am-muted);
}

.agents-side {
  display: grid;
  gap: 12px;
  align-content: start;
}

.side-card {
  padding: 14px;
}

.side-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.side-title span {
  font-weight: 800;
}

.side-title b {
  color: var(--am-primary);
}

.enabled-list {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.enabled-list button {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) 8px;
  gap: 8px;
  align-items: center;
  padding: 8px;
  text-align: left;
  cursor: pointer;
  background: #faf9ff;
  border: 0;
  border-radius: 10px;
}

.small-avatar {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  font-size: 9px;
  font-weight: 800;
  color: var(--am-primary);
  background: var(--am-primary-soft);
  border-radius: 9px;
}

.enabled-list b,
.enabled-list small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.enabled-list b {
  font-size: 9px;
}

.enabled-list small {
  margin-top: 2px;
  font-size: 8px;
  color: var(--am-muted);
}

.enabled-list i {
  width: 7px;
  height: 7px;
  background: var(--am-success);
  border-radius: 50%;
}

.chain {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.chain > div {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  padding: 8px;
  border: 1px solid var(--am-border);
  border-radius: 10px;
}

.chain > div > span {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  font-size: 9px;
  font-weight: 800;
  color: var(--am-primary);
  background: var(--am-primary-soft);
  border-radius: 9px;
}

.chain b,
.chain small {
  display: block;
}

.chain b {
  font-size: 9px;
}

.chain small {
  margin-top: 2px;
  font-size: 8px;
  color: var(--am-muted);
}

.detail-head {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 18px;
}

.detail-head h2 {
  margin: 0 0 6px;
}

.drawer-section {
  margin-top: 20px;
}

.drawer-section > b {
  display: block;
  margin-bottom: 10px;
}

@media (max-width: 1300px) {
  .agent-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1000px) {
  .agents-layout {
    grid-template-columns: 1fr;
  }

  .agents-side {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .agent-grid,
  .agents-side {
    grid-template-columns: 1fr;
  }
}
</style>
