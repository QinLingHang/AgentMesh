<script setup lang="ts">
import type {
  EcosystemOverview,
  EcosystemPackage,
  EcosystemPackageBundle,
  EcosystemPackageManifest,
  ProjectPackageInstallation,
  ServiceAccount,
} from '#/api/agentmesh';

import { computed, onMounted, reactive, ref, watch } from 'vue';

import { ElMessage, ElMessageBox } from 'element-plus';

import {
  createEcosystemPackage,
  createServiceAccount,
  deleteProjectInstallation,
  exportEcosystemPackage,
  friendlyApiError,
  getEcosystemOverview,
  importEcosystemPackage,
  installEcosystemPackage,
  listProjectInstallations,
  listServiceAccounts,
  revokeServiceAccount,
  searchEcosystemPackages,
  setProjectInstallationEnabled,
  validateEcosystemPackage,
} from '#/api/agentmesh';
import MetricCard from '#/components/agentmesh/MetricCard.vue';
import PageHeader from '#/components/agentmesh/PageHeader.vue';
import { useAgentMeshResourcesStore } from '#/store/agentmesh-resources';

const resources = useAgentMeshResourcesStore();
const overview = ref<EcosystemOverview | null>(null);
const packages = ref<EcosystemPackage[]>([]);
const installations = ref<ProjectPackageInstallation[]>([]);
const serviceAccounts = ref<ServiceAccount[]>([]);
const projectId = ref<null | number>(null);
const tab = ref<'api' | 'installed' | 'marketplace' | 'publisher'>(
  'marketplace',
);
const query = ref('');
const kind = ref('');
const accountOpen = ref(false);
const accountForm = reactive({
  name: 'automation',
  scopes: 'tasks:run,knowledge:read',
  expiresAt: '',
});
const latestCredential = ref('');
const publisherForm = reactive({
  slug: 'my-agent',
  name: '我的 Agent 模板',
  kind: 'AGENT' as 'AGENT' | 'MCP' | 'PLUGIN',
  summary: '',
  description: '',
  visibility: 'PRIVATE' as 'PRIVATE' | 'PUBLIC',
  version: '1.0.0',
  publish: false,
});
const manifestJson = ref(
  JSON.stringify(
    {
      schemaVersion: 'v1',
      kind: 'AGENT',
      permissions: [],
      agent: {
        name: 'MyAgent',
        description: 'Agent template',
        capabilities: ['general'],
      },
    },
    null,
    2,
  ),
);
const bundleJson = ref('');
const validationResult = ref('');

const selectedProject = computed(
  () => resources.projects.find((item) => item.id === projectId.value) ?? null,
);

async function reloadMarket() {
  overview.value = await getEcosystemOverview();
  packages.value = await searchEcosystemPackages(query.value, kind.value);
}
async function reloadProject() {
  if (projectId.value === null || projectId.value === undefined) {
    installations.value = [];
    serviceAccounts.value = [];
    return;
  }
  const [installed, accounts] = await Promise.all([
    listProjectInstallations(projectId.value),
    listServiceAccounts(projectId.value),
  ]);
  installations.value = installed;
  serviceAccounts.value = accounts;
}
async function install(pkg: EcosystemPackage) {
  if (projectId.value === null || projectId.value === undefined)
    return ElMessage.warning('请先选择目标项目');
  try {
    await installEcosystemPackage(
      projectId.value,
      pkg.slug,
      pkg.latestVersion || '',
    );
    await reloadProject();
    ElMessage.success('已安装到项目');
    tab.value = 'installed';
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '安装失败'));
  }
}
async function toggleInstallation(
  item: ProjectPackageInstallation,
  enabled: boolean,
) {
  if (projectId.value === null || projectId.value === undefined) return;
  try {
    await setProjectInstallationEnabled(projectId.value, item.id, enabled);
    await reloadProject();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '更新失败'));
  }
}
async function removeInstallation(item: ProjectPackageInstallation) {
  if (projectId.value === null || projectId.value === undefined) return;
  await ElMessageBox.confirm(`从项目移除 ${item.packageName}？`, '移除安装', {
    type: 'warning',
  });
  try {
    await deleteProjectInstallation(projectId.value, item.id);
    await reloadProject();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '移除失败'));
  }
}
async function createAccount() {
  if (projectId.value === null || projectId.value === undefined) return;
  try {
    const credential = await createServiceAccount(
      projectId.value,
      accountForm.name.trim(),
      accountForm.scopes
        .split(',')
        .map((v) => v.trim())
        .filter(Boolean),
      accountForm.expiresAt || null,
    );
    latestCredential.value = credential.apiKey;
    accountOpen.value = false;
    await reloadProject();
    ElMessage.success('Service Account 已创建；请立即保存 API Key');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '创建 Service Account 失败'));
  }
}
async function revoke(account: ServiceAccount) {
  if (projectId.value === null || projectId.value === undefined) return;
  await ElMessageBox.confirm(`撤销 ${account.name}？`, '撤销 Service Account', {
    type: 'warning',
  });
  try {
    await revokeServiceAccount(projectId.value, account.id);
    await reloadProject();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '撤销失败'));
  }
}

function parseManifest(): EcosystemPackageManifest {
  const parsed = JSON.parse(manifestJson.value) as EcosystemPackageManifest;
  if (!parsed || typeof parsed !== 'object')
    throw new Error('Manifest 必须是 JSON 对象');
  parsed.kind = publisherForm.kind;
  return parsed;
}
async function validatePackage() {
  try {
    const result = await validateEcosystemPackage(
      publisherForm.kind,
      parseManifest(),
    );
    validationResult.value = JSON.stringify(result, null, 2);
    ElMessage.success(
      result.valid ? 'Manifest 校验通过' : 'Manifest 校验未通过',
    );
  } catch (error) {
    ElMessage.error(friendlyApiError(error, 'Manifest 校验失败'));
  }
}
async function publishPackage() {
  try {
    await createEcosystemPackage({
      ...publisherForm,
      manifest: parseManifest(),
    });
    await reloadMarket();
    ElMessage.success('生态包已创建');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '创建生态包失败'));
  }
}
async function exportPackage(pkg: EcosystemPackage) {
  try {
    const bundle = await exportEcosystemPackage(
      pkg.slug,
      pkg.latestVersion || '',
    );
    bundleJson.value = JSON.stringify(bundle, null, 2);
    tab.value = 'publisher';
    ElMessage.success('生态包已导出到编辑区');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '导出失败'));
  }
}
async function importPackage() {
  try {
    const bundle = JSON.parse(bundleJson.value) as EcosystemPackageBundle;
    await importEcosystemPackage(bundle);
    await reloadMarket();
    ElMessage.success('生态包已导入');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '导入失败'));
  }
}

watch(projectId, reloadProject);
onMounted(async () => {
  await resources.refreshProjects();
  projectId.value = resources.projects[0]?.id ?? null;
  await Promise.all([reloadMarket(), reloadProject()]);
});
</script>

<template>
  <div class="am-page ecosystem-page">
    <PageHeader
      eyebrow="PLATFORM ECOSYSTEM"
      title="生态中心"
      description="发布、发现和安装 Agent、MCP 与插件；同时使用项目级服务账号和官方 SDK 接入业务系统。"
    >
      <el-select
        v-model="projectId"
        placeholder="目标项目"
        style="width: 220px"
      >
        <el-option
          v-for="project in resources.projects"
          :key="project.id"
          :label="project.name"
          :value="project.id"
        />
      </el-select>
    </PageHeader>

    <div class="am-metrics">
      <MetricCard
        label="已发布"
        :value="overview?.publishedPackages ?? 0"
        hint="生态包"
      /><MetricCard
        label="Agent"
        :value="overview?.agentPackages ?? 0"
      /><MetricCard
        label="MCP"
        :value="overview?.mcpPackages ?? 0"
      /><MetricCard
        label="累计安装"
        :value="overview?.totalInstalls ?? 0"
        tone="primary"
      />
    </div>

    <el-tabs v-model="tab" class="eco-tabs">
      <el-tab-pane label="生态市场" name="marketplace" /><el-tab-pane
        label="项目已安装"
        name="installed"
      /><el-tab-pane label="API 与 SDK" name="api" /><el-tab-pane
        label="发布者中心"
        name="publisher"
      />
    </el-tabs>

    <section v-if="tab === 'marketplace'" class="am-card eco-panel">
      <div class="market-filter">
        <el-input
          v-model="query"
          clearable
          placeholder="搜索 Agent、MCP、插件…"
          @keyup.enter="reloadMarket"
        /><el-select
          v-model="kind"
          clearable
          placeholder="全部类型"
          style="width: 150px"
          @change="reloadMarket"
        >
          <el-option label="Agent" value="AGENT" /><el-option
            label="MCP"
            value="MCP"
          /><el-option label="插件" value="PLUGIN" />
</el-select><el-button type="primary" @click="reloadMarket">搜索</el-button>
      </div>
      <div class="package-grid">
        <article v-for="pkg in packages" :key="pkg.id" class="package-card">
          <div class="package-head">
            <el-tag round>{{ pkg.kind }}</el-tag><span>v{{ pkg.latestVersion || '—' }}</span>
          </div>
          <h3>{{ pkg.name }}</h3>
          <p>{{ pkg.summary || pkg.description }}</p>
          <div class="package-meta">
            <span>{{ pkg.slug }}</span><span>{{ pkg.installCount }} 次安装</span>
          </div>
          <div class="package-actions">
            <el-button type="primary" @click="install(pkg)">
              安装到项目
</el-button><el-button @click="exportPackage(pkg)">导出</el-button>
          </div>
        </article>
      </div>
      <div v-if="packages.length === 0" class="am-empty">没有匹配的生态包</div>
    </section>

    <section v-else-if="tab === 'installed'" class="am-card eco-panel">
      <div class="panel-head">
        <div>
          <h2>{{ selectedProject?.name || '项目' }} · 已安装</h2>
          <p>启用或停用已安装的 Agent、MCP 与插件。</p>
        </div>
      </div>
      <el-table v-if="installations.length" :data="installations">
        <el-table-column
          prop="packageName"
          label="名称"
          min-width="180"
        /><el-table-column
          prop="kind"
          label="类型"
          width="100"
        /><el-table-column
          prop="version"
          label="版本"
          width="110"
        /><el-table-column label="启用" width="100">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled"
              @change="toggleInstallation(row, Boolean($event))"
            />
          </template>
</el-table-column><el-table-column label="资源" min-width="140">
          <template #default="{ row }">
            {{ row.resourceType || '—' }} {{ row.resourceId || '' }}
          </template>
</el-table-column><el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button link type="danger" @click="removeInstallation(row)">
              移除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="am-empty">当前项目还没有安装生态包</div>
    </section>

    <section v-else-if="tab === 'api'" class="api-grid">
      <div class="am-card api-card">
        <div class="panel-head">
          <div>
            <h2>Service Accounts</h2>
            <p>为 CI、后台服务或第三方系统创建项目级 API 身份。</p>
          </div>
          <el-button
            type="primary"
            :disabled="!projectId"
            @click="accountOpen = true"
          >
            ＋ 创建账号
          </el-button>
        </div>
        <div v-if="latestCredential" class="credential-warning">
          <b>刚创建的 API Key</b><code>{{ latestCredential }}</code><span>该明文只应展示一次，请立即保存。</span>
        </div>
        <div class="account-list">
          <div
            v-for="account in serviceAccounts"
            :key="account.id"
            class="account-row"
          >
            <div>
              <b>{{ account.name }}</b><small>{{ account.keyPrefix }}… ·
                {{ account.scopes.join(', ') }}</small>
            </div>
            <div>
              <span>{{ account.requestCount }} requests</span><el-button link type="danger" @click="revoke(account)">
                撤销
              </el-button>
            </div>
          </div>
        </div>
        <div v-if="serviceAccounts.length === 0" class="mini-empty">
          还没有 Service Account
        </div>
      </div>
      <div class="am-card api-card">
        <h2>SDK 接入</h2>
        <p>
          AgentMesh 提供 Python / TypeScript SDK。Service Account 只授予声明过的
          scopes。
        </p>
        <pre>
AgentMesh Client
  baseURL: /api
  auth: Service Account

Run Task → Runtime
Knowledge → RAG
Tool / MCP → Governance</pre>
      </div>
    </section>

    <section v-else class="publisher-grid">
      <div class="am-card api-card">
        <div class="panel-head">
          <div>
            <h2>创建 / 发布生态包</h2>
            <p>
              支持 Agent、MCP 与 Plugin，发布前可先执行服务端 Manifest 校验。
            </p>
          </div>
        </div>
        <el-form label-position="top" class="publisher-form">
          <div class="grid-2">
            <el-form-item label="Slug">
              <el-input v-model="publisherForm.slug" />
</el-form-item><el-form-item label="名称">
              <el-input v-model="publisherForm.name" />
</el-form-item><el-form-item label="类型">
              <el-select v-model="publisherForm.kind" style="width: 100%">
                <el-option label="Agent" value="AGENT" /><el-option
                  label="MCP"
                  value="MCP"
                /><el-option label="Plugin" value="PLUGIN" />
              </el-select>
</el-form-item><el-form-item label="版本">
              <el-input v-model="publisherForm.version" />
</el-form-item><el-form-item label="可见性">
              <el-select v-model="publisherForm.visibility" style="width: 100%">
                <el-option label="Private" value="PRIVATE" /><el-option
                  label="Public"
                  value="PUBLIC"
                />
              </el-select>
</el-form-item><el-form-item label="立即发布">
              <el-switch v-model="publisherForm.publish" />
            </el-form-item>
          </div>
          <el-form-item label="摘要">
            <el-input v-model="publisherForm.summary" />
</el-form-item><el-form-item label="描述">
            <el-input
              v-model="publisherForm.description"
              type="textarea"
              :rows="2"
            />
</el-form-item><el-form-item label="Manifest JSON">
            <el-input v-model="manifestJson" type="textarea" :rows="11" />
          </el-form-item>
          <div style="display: flex; gap: 8px">
            <el-button @click="validatePackage">校验 Manifest</el-button><el-button type="primary" @click="publishPackage">
              创建生态包
            </el-button>
          </div>
        </el-form>
        <pre v-if="validationResult" style="margin-top: 12px">{{
          validationResult
        }}</pre>
      </div>
      <div class="am-card api-card">
        <h2>导入 / 导出</h2>
        <p>
          从市场点击“导出”会把 Bundle 放到这里；也可以粘贴 Bundle JSON 后导入。
        </p>
        <el-input
          v-model="bundleJson"
          type="textarea"
          :rows="18"
          style="margin-top: 12px"
        /><el-button
          type="primary"
          style="width: 100%; margin-top: 10px"
          @click="importPackage"
        >
          导入 Bundle
        </el-button>
      </div>
    </section>
  </div>

  <el-dialog v-model="accountOpen" title="创建 Service Account" width="520px">
    <el-form label-position="top">
      <el-form-item label="名称">
        <el-input v-model="accountForm.name" />
</el-form-item><el-form-item label="Scopes（逗号分隔）">
        <el-input v-model="accountForm.scopes" />
</el-form-item><el-form-item label="过期时间（可选）">
        <el-input
          v-model="accountForm.expiresAt"
          placeholder="2027-01-01T00:00:00Z"
        />
      </el-form-item>
</el-form><template #footer>
      <el-button @click="accountOpen = false">取消</el-button><el-button type="primary" @click="createAccount"> 创建 </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.eco-tabs {
  margin-top: 18px;
}

.eco-panel,
.api-card {
  padding: 16px;
}

.market-filter {
  display: flex;
  gap: 8px;
}

.package-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.package-card {
  padding: 15px;
  background: #fff;
  border: 1px solid var(--am-border);
  border-radius: 13px;
}

.package-head {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  color: var(--am-muted);
}

.package-card h3 {
  margin: 14px 0 5px;
}

.package-card p {
  min-height: 42px;
  margin: 0;
  font-size: 10px;
  line-height: 1.7;
  color: var(--am-muted);
}

.package-meta {
  display: flex;
  gap: 8px;
  justify-content: space-between;
  margin-top: 18px;
  font-size: 8px;
  color: var(--am-muted);
}

.package-actions {
  margin-top: 10px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.panel-head h2,
.api-card h2 {
  margin: 0;
  font-size: 16px;
}

.panel-head p,
.api-card > p {
  margin: 4px 0 0;
  font-size: 10px;
  color: var(--am-muted);
}

.api-grid,
.publisher-grid {
  display: grid;
  grid-template-columns: 1.4fr 0.8fr;
  gap: 14px;
}

.publisher-form {
  margin-top: 14px;
}

.grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.credential-warning {
  display: grid;
  gap: 5px;
  padding: 12px;
  margin: 12px 0;
  font-size: 10px;
  background: #faf8ff;
  border: 1px solid #ded5ff;
  border-radius: 11px;
}

.credential-warning code {
  padding: 8px;
  color: #f0edff;
  word-break: break-all;
  background: #1c1d28;
  border-radius: 8px;
}

.credential-warning span {
  color: var(--am-danger);
}

.account-list {
  display: grid;
  gap: 7px;
  margin-top: 12px;
}

.account-row {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  padding: 10px;
  border: 1px solid var(--am-border);
  border-radius: 10px;
}

.account-row b,
.account-row small {
  display: block;
}

.account-row b {
  font-size: 10px;
}

.account-row small {
  margin-top: 3px;
  font-size: 8px;
  color: var(--am-muted);
}

.account-row > div:last-child {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 8px;
  color: var(--am-muted);
}

.mini-empty {
  padding: 20px;
  font-size: 10px;
  color: var(--am-muted);
  text-align: center;
}

.api-card pre {
  padding: 14px;
  margin: 16px 0 0;
  overflow: auto;
  font-size: 10px;
  line-height: 1.8;
  color: #e9e7ff;
  background: #1c1d28;
  border-radius: 12px;
}

@media (max-width: 1000px) {
  .package-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .api-grid,
  .publisher-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 650px) {
  .market-filter {
    flex-direction: column;
  }

  .market-filter :deep(.el-select) {
    width: 100% !important;
  }

  .package-grid {
    grid-template-columns: 1fr;
  }
}
</style>
