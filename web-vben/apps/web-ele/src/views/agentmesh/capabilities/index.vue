<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';

import { ElMessage, ElMessageBox } from 'element-plus';

import {
  createMCPServer,
  createTool,
  deleteMCPServer,
  deleteTool,
  discoverMCPTools,
  friendlyApiError,
  seedDemoMCPServer,
  seedDemoTools,
  seedDesktopTools,
  updateTool,
} from '#/api/agentmesh';
import MetricCard from '#/components/agentmesh/MetricCard.vue';
import PageHeader from '#/components/agentmesh/PageHeader.vue';
import StatusBadge from '#/components/agentmesh/StatusBadge.vue';
import { useAgentMeshResourcesStore } from '#/store/agentmesh-resources';

const resources = useAgentMeshResourcesStore();
const tab = ref<'mcp' | 'plugins' | 'tools'>('tools');
const query = ref('');
const toolOpen = ref(false);
const mcpOpen = ref(false);
const toolForm = reactive({
  name: 'custom.tool',
  description: '自定义工具',
  protocol: 'http',
  endpoint: '',
  riskLevel: 'low',
  requiresConfirmation: false,
  enabled: true,
  inputSchema: '{"type":"object","properties":{}}',
});
const mcpForm = reactive({
  name: 'MCP Server',
  endpoint: 'http://127.0.0.1:9000/mcp',
  connectTimeoutMs: 5000,
  callTimeoutMs: 30_000,
});
const discovered = ref<
  Record<number, Awaited<ReturnType<typeof discoverMCPTools>>>
>({});

const filteredTools = computed(() => {
  const keyword = query.value.trim().toLowerCase();
  return resources.tools.filter(
    (item) =>
      !keyword ||
      [item.name, item.description, item.protocol, item.riskLevel]
        .join(' ')
        .toLowerCase()
        .includes(keyword),
  );
});
const filteredMcp = computed(() => {
  const keyword = query.value.trim().toLowerCase();
  return resources.mcpServers.filter(
    (item) =>
      !keyword ||
      [item.name, item.endpoint, item.transport]
        .join(' ')
        .toLowerCase()
        .includes(keyword),
  );
});

async function createNewTool() {
  try {
    await createTool({
      ...toolForm,
      inputSchema: JSON.parse(toolForm.inputSchema),
    });
    toolOpen.value = false;
    await resources.refreshTools();
    ElMessage.success('工具已添加');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '添加工具失败'));
  }
}
async function toggleTool(tool: (typeof resources.tools)[number]) {
  try {
    await updateTool(tool.id, { ...tool, enabled: !tool.enabled });
    await resources.refreshTools();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '更新失败'));
  }
}
async function removeTool(tool: (typeof resources.tools)[number]) {
  await ElMessageBox.confirm(`删除工具 ${tool.name}？`, '删除工具', {
    type: 'warning',
  });
  try {
    await deleteTool(tool.id);
    await resources.refreshTools();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '删除失败'));
  }
}
async function createNewMcp() {
  try {
    await createMCPServer({
      ...mcpForm,
      transport: 'streamable_http',
      enabled: true,
    });
    mcpOpen.value = false;
    await resources.refreshMcp();
    ElMessage.success('MCP Server 已添加');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '添加 MCP 失败'));
  }
}
async function removeMcp(server: (typeof resources.mcpServers)[number]) {
  await ElMessageBox.confirm(`删除 MCP Server ${server.name}？`, '删除连接', {
    type: 'warning',
  });
  try {
    await deleteMCPServer(server.id);
    await resources.refreshMcp();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '删除失败'));
  }
}
async function discover(server: (typeof resources.mcpServers)[number]) {
  try {
    discovered.value[server.id] = await discoverMCPTools(server.id);
    ElMessage.success(
      `发现 ${discovered.value[server.id]?.length ?? 0} 个工具`,
    );
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '发现失败'));
  }
}
async function seedTools() {
  try {
    await seedDemoTools();
    await resources.refreshTools();
  } catch (error) {
    ElMessage.error(friendlyApiError(error));
  }
}
async function seedDesktop() {
  try {
    await seedDesktopTools();
    await resources.refreshTools();
  } catch (error) {
    ElMessage.error(friendlyApiError(error));
  }
}
async function seedMcp() {
  try {
    await seedDemoMCPServer();
    await resources.refreshMcp();
  } catch (error) {
    ElMessage.error(friendlyApiError(error));
  }
}

onMounted(() =>
  Promise.all([
    resources.refreshTools(),
    resources.refreshMcp(),
    resources.refreshPlugins(),
  ]),
);
</script>

<template>
  <div class="am-page capability-page">
    <PageHeader
      eyebrow="CAPABILITY CENTER"
      title="工具 / MCP"
      description="集中管理智能体可调用的确定性工具、MCP Server 与平台扩展。"
    >
      <el-button v-if="tab === 'tools'" @click="seedTools">演示工具</el-button><el-button v-if="tab === 'tools'" @click="seedDesktop">
        Desktop Tools
</el-button><el-button v-if="tab === 'mcp'" @click="seedMcp">演示 MCP</el-button><el-button
        type="primary"
        @click="tab === 'mcp' ? (mcpOpen = true) : (toolOpen = true)"
      >
        ＋ {{ tab === 'mcp' ? '添加连接' : '添加工具' }}
      </el-button>
    </PageHeader>
    <div class="am-metrics">
      <MetricCard
        label="工具"
        :value="resources.tools.length"
        :hint="`${resources.enabledTools.length} 已启用`"
      /><MetricCard
        label="MCP Server"
        :value="resources.mcpServers.length"
        :hint="`${resources.enabledMcp.length} 已启用`"
      /><MetricCard
        label="平台能力"
        :value="resources.plugins.length"
        hint="Runtime 扩展"
      /><MetricCard
        label="高风险工具"
        :value="
          resources.tools.filter((item) => item.requiresConfirmation).length
        "
        tone="primary"
        hint="需要人工确认"
      />
    </div>
    <el-tabs v-model="tab" class="cap-tabs">
      <el-tab-pane label="工具" name="tools" /><el-tab-pane
        label="MCP"
        name="mcp"
      /><el-tab-pane label="平台能力" name="plugins" />
    </el-tabs>
    <div class="cap-layout">
      <main>
        <div class="am-card cap-search">
          <el-input
            v-model="query"
            clearable
            placeholder="搜索工具、MCP 或平台能力…"
          />
        </div>
        <div v-if="tab === 'tools'" class="cap-grid">
          <article
            v-for="tool in filteredTools"
            :key="tool.id"
            class="am-card cap-card"
          >
            <div class="card-head">
              <div class="cap-icon">◇</div>
              <el-switch
                :model-value="tool.enabled"
                @change="toggleTool(tool)"
              />
            </div>
            <h3>{{ tool.name }}</h3>
            <p>{{ tool.description }}</p>
            <div class="tag-row">
              <el-tag round>{{ tool.protocol }}</el-tag><el-tag
                round
                :type="tool.requiresConfirmation ? 'warning' : 'info'"
              >
                {{ tool.riskLevel }}
              </el-tag>
            </div>
            <div class="card-foot">
              <span>{{
                tool.requiresConfirmation ? '执行前需要确认' : '可直接调用'
              }}</span><el-button link type="danger" @click="removeTool(tool)">
                删除
              </el-button>
            </div>
          </article>
        </div>
        <div v-if="tab === 'mcp'" class="cap-grid">
          <article
            v-for="server in filteredMcp"
            :key="server.id"
            class="am-card cap-card"
          >
            <div class="card-head">
              <div class="cap-icon">MC</div>
              <StatusBadge :status="server.enabled ? 'ENABLED' : 'DISABLED'" />
            </div>
            <h3>{{ server.name }}</h3>
            <p>{{ server.endpoint }}</p>
            <div class="tag-row">
              <el-tag>{{ server.transport }}</el-tag><el-tag type="info">{{ server.callTimeoutMs }}ms</el-tag>
            </div>
            <div v-if="discovered[server.id]?.length" class="discovered">
              <span v-for="item in discovered[server.id]" :key="item.name">{{
                item.name
              }}</span>
            </div>
            <div class="card-foot">
              <el-button link type="primary" @click="discover(server)">
                发现工具
</el-button><el-button link type="danger" @click="removeMcp(server)">
                删除
              </el-button>
            </div>
          </article>
        </div>
        <div v-if="tab === 'plugins'" class="cap-grid">
          <article
            v-for="plugin in resources.plugins"
            :key="plugin.id"
            class="am-card cap-card"
          >
            <div class="card-head">
              <div class="cap-icon">✦</div>
              <StatusBadge :status="plugin.status" />
            </div>
            <h3>{{ plugin.name }}</h3>
            <p>
              {{ plugin.provider || 'AgentMesh Runtime' }} ·
              {{ plugin.model || '平台扩展' }}
            </p>
            <div class="tag-row">
              <el-tag>{{ plugin.kind }}</el-tag><el-tag type="info">v{{ plugin.version }}</el-tag>
            </div>
          </article>
        </div>
      </main>
      <aside class="cap-side">
        <section class="am-card side-card">
          <div class="side-title">当前能力</div>
          <div class="side-big">
            {{
              resources.tools.length +
              resources.mcpServers.length +
              resources.plugins.length
            }}
          </div>
          <div class="mini-grid">
            <div>
              <span>Tool</span><b>{{ resources.tools.length }}</b>
            </div>
            <div>
              <span>MCP</span><b>{{ resources.mcpServers.length }}</b>
            </div>
            <div>
              <span>Platform</span><b>{{ resources.plugins.length }}</b>
            </div>
          </div>
        </section>
        <section class="am-card side-card">
          <div class="side-title">已启用工具</div>
          <div
            class="enabled-row"
            v-for="tool in resources.enabledTools.slice(0, 8)"
            :key="tool.id"
          >
            <span class="small-icon">◇</span><span><b>{{ tool.name }}</b><small>{{ tool.description }}</small></span><i></i>
          </div>
        </section>
      </aside>
    </div>
  </div>

  <el-dialog v-model="toolOpen" title="添加工具" width="560px">
    <el-form label-position="top">
      <el-form-item label="名称">
        <el-input v-model="toolForm.name" />
</el-form-item><el-form-item label="描述">
        <el-input v-model="toolForm.description" />
</el-form-item><el-form-item label="协议">
        <el-input v-model="toolForm.protocol" />
</el-form-item><el-form-item label="Endpoint">
        <el-input v-model="toolForm.endpoint" />
</el-form-item><el-form-item label="风险等级">
        <el-select v-model="toolForm.riskLevel" style="width: 100%">
          <el-option label="low" value="low" /><el-option
            label="medium"
            value="medium"
          /><el-option label="high" value="high" />
        </el-select>
</el-form-item><el-checkbox v-model="toolForm.requiresConfirmation">
        需要人工确认
</el-checkbox><el-form-item label="Input Schema" style="margin-top: 12px">
        <el-input v-model="toolForm.inputSchema" type="textarea" :rows="4" />
      </el-form-item>
</el-form><template #footer>
      <el-button @click="toolOpen = false">取消</el-button><el-button type="primary" @click="createNewTool"> 添加 </el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="mcpOpen" title="添加 MCP Server" width="520px">
    <el-form label-position="top">
      <el-form-item label="名称">
        <el-input v-model="mcpForm.name" />
</el-form-item><el-form-item label="Endpoint">
        <el-input v-model="mcpForm.endpoint" />
</el-form-item><el-form-item label="连接超时">
        <el-input-number
          v-model="mcpForm.connectTimeoutMs"
          :min="100"
          style="width: 100%"
        />
</el-form-item><el-form-item label="调用超时">
        <el-input-number
          v-model="mcpForm.callTimeoutMs"
          :min="1000"
          style="width: 100%"
        />
      </el-form-item>
</el-form><template #footer>
      <el-button @click="mcpOpen = false">取消</el-button><el-button type="primary" @click="createNewMcp"> 添加 </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.cap-tabs {
  margin-top: 18px;
}

.cap-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 275px;
  gap: 16px;
}

.cap-search {
  padding: 10px;
  margin-bottom: 12px;
  box-shadow: none;
}

.cap-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.cap-card {
  min-height: 175px;
  padding: 15px;
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.cap-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  font-weight: 850;
  color: var(--am-primary);
  background: var(--am-primary-soft);
  border-radius: 11px;
}

.cap-card h3 {
  margin: 13px 0 4px;
  font-size: 15px;
}

.cap-card p {
  min-height: 36px;
  margin: 0;
  font-size: 10px;
  line-height: 1.6;
  color: var(--am-muted);
  word-break: break-all;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 10px;
}

.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 10px;
  margin-top: 13px;
  font-size: 9px;
  color: var(--am-muted);
  border-top: 1px solid var(--am-border);
}

.discovered {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}

.discovered span {
  padding: 4px 6px;
  font-size: 8px;
  background: #f8f7fd;
  border-radius: 7px;
}

.cap-side {
  display: grid;
  gap: 12px;
  align-content: start;
}

.side-card {
  padding: 14px;
}

.side-title {
  font-size: 10px;
  font-weight: 800;
}

.side-big {
  margin: 8px 0;
  font-size: 28px;
  font-weight: 850;
}

.mini-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

.mini-grid > div {
  padding: 9px;
  text-align: center;
  background: #faf9ff;
  border-radius: 9px;
}

.mini-grid span,
.mini-grid b {
  display: block;
}

.mini-grid span {
  font-size: 8px;
  color: var(--am-muted);
}

.mini-grid b {
  margin-top: 3px;
}

.enabled-row {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) 7px;
  gap: 7px;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--am-border);
}

.small-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  color: var(--am-primary);
  background: var(--am-primary-soft);
  border-radius: 8px;
}

.enabled-row b,
.enabled-row small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.enabled-row b {
  font-size: 9px;
}

.enabled-row small {
  margin-top: 2px;
  font-size: 8px;
  color: var(--am-muted);
}

.enabled-row i {
  width: 7px;
  height: 7px;
  background: var(--am-success);
  border-radius: 50%;
}

@media (max-width: 1200px) {
  .cap-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 950px) {
  .cap-layout {
    grid-template-columns: 1fr;
  }

  .cap-side {
    display: none;
  }
}

@media (max-width: 650px) {
  .cap-grid {
    grid-template-columns: 1fr;
  }
}
</style>
