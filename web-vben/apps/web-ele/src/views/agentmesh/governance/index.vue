<script setup lang="ts">
import type {
  CostSummary,
  GovernanceOverview,
  Organization,
  Project,
  ProjectQuota,
} from '#/api/agentmesh';

import { computed, onMounted, reactive, ref, watch } from 'vue';

import { ElMessage, ElMessageBox } from 'element-plus';

import {
  addOrganizationMember,
  addProjectMember,
  bindOrganizationProject,
  createOrganization,
  createProjectSecret,
  deleteProjectSecret,
  friendlyApiError,
  getProjectCostSummary,
  getProjectGovernance,
  listOrganizations,
  removeProjectMember,
  updateProjectQuota,
  upsertProjectModelProvider,
} from '#/api/agentmesh';
import MetricCard from '#/components/agentmesh/MetricCard.vue';
import PageHeader from '#/components/agentmesh/PageHeader.vue';
import { useAgentMeshResourcesStore } from '#/store/agentmesh-resources';

const resources = useAgentMeshResourcesStore();
const projectId = ref<null | number>(null);
const overview = ref<GovernanceOverview | null>(null);
const cost = ref<CostSummary | null>(null);
const organizations = ref<Organization[]>([]);
const loading = ref(false);
const memberEmail = ref('');
const memberRole = ref('DEVELOPER');
const teamName = ref('');
const orgMemberEmail = ref('');
const orgRole = ref('MEMBER');
const secretOpen = ref(false);
const secretForm = reactive({
  name: 'runtime-key',
  kind: 'API_KEY',
  value: '',
});
const providerForm = reactive({
  provider: 'openai-compatible',
  baseUrl: '',
  modelName: '',
  secretId: null as null | number,
  enabled: true,
});

const selectedProject = computed<null | Project>(
  () => resources.projects.find((item) => item.id === projectId.value) ?? null,
);
const usagePercent = computed(() => {
  if (!overview.value?.quota.monthlyTokenLimit) return 0;
  return Math.min(
    100,
    Math.round(
      (overview.value.usage.tokenCount /
        overview.value.quota.monthlyTokenLimit) *
        100,
    ),
  );
});

async function reload() {
  if (projectId.value === null || projectId.value === undefined) return;
  loading.value = true;
  try {
    const [g, c, orgs] = await Promise.all([
      getProjectGovernance(projectId.value),
      getProjectCostSummary(projectId.value),
      listOrganizations(),
    ]);
    overview.value = g;
    cost.value = c;
    organizations.value = orgs;
    if (g.modelProvider) Object.assign(providerForm, g.modelProvider);
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '治理数据加载失败'));
  } finally {
    loading.value = false;
  }
}
async function addMember() {
  if (
    projectId.value === null ||
    projectId.value === undefined ||
    !memberEmail.value.trim()
  )
    return;
  try {
    await addProjectMember(
      projectId.value,
      memberEmail.value.trim(),
      memberRole.value,
    );
    memberEmail.value = '';
    await reload();
    ElMessage.success('成员已添加');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '添加成员失败'));
  }
}
async function removeMember(userId: number) {
  if (projectId.value === null || projectId.value === undefined) return;
  await ElMessageBox.confirm('移除该项目成员？', '移除成员', {
    type: 'warning',
  });
  try {
    await removeProjectMember(projectId.value, userId);
    await reload();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '移除失败'));
  }
}
async function saveQuota() {
  if (
    projectId.value === null ||
    projectId.value === undefined ||
    !overview.value
  )
    return;
  try {
    await updateProjectQuota(
      projectId.value,
      overview.value.quota as ProjectQuota,
    );
    await reload();
    ElMessage.success('项目额度已保存');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '保存额度失败'));
  }
}
async function addSecret() {
  if (projectId.value === null || projectId.value === undefined) return;
  try {
    await createProjectSecret(
      projectId.value,
      secretForm.name.trim(),
      secretForm.kind,
      secretForm.value,
    );
    secretOpen.value = false;
    secretForm.value = '';
    await reload();
    ElMessage.success('密钥已创建');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '创建密钥失败'));
  }
}
async function removeSecret(id: number) {
  if (projectId.value === null || projectId.value === undefined) return;
  await ElMessageBox.confirm('删除该项目密钥？', '删除密钥', {
    type: 'warning',
  });
  try {
    await deleteProjectSecret(projectId.value, id);
    await reload();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '删除失败'));
  }
}
async function saveProvider() {
  if (projectId.value === null || projectId.value === undefined) return;
  try {
    await upsertProjectModelProvider(projectId.value, {
      projectId: projectId.value,
      ...providerForm,
    });
    await reload();
    ElMessage.success('项目模型配置已保存');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '保存模型配置失败'));
  }
}
async function createTeam() {
  if (!teamName.value.trim()) return;
  try {
    await createOrganization(teamName.value.trim());
    teamName.value = '';
    organizations.value = await listOrganizations();
    ElMessage.success('团队已创建');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '创建团队失败'));
  }
}
async function addOrgMember(orgId: number) {
  if (!orgMemberEmail.value.trim()) return;
  try {
    await addOrganizationMember(
      orgId,
      orgMemberEmail.value.trim(),
      orgRole.value,
    );
    orgMemberEmail.value = '';
    ElMessage.success('组织成员已添加');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '添加组织成员失败'));
  }
}
async function bindProject(orgId: number) {
  if (projectId.value === null || projectId.value === undefined) return;
  try {
    await bindOrganizationProject(orgId, projectId.value);
    ElMessage.success('当前项目已绑定到组织');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '绑定失败'));
  }
}
function roleLabel(role?: string) {
  const map: Record<string, string> = {
    OWNER: '所有者',
    ADMIN: '管理员',
    DEVELOPER: '开发成员',
    VIEWER: '只读成员',
  };
  return role ? (map[role] ?? role) : '—';
}
function auditTone(result: string) {
  const upper = result.toUpperCase();
  if (['COMPLETED', 'SUCCESS'].includes(upper)) return 'success';
  if (['DENIED', 'FAILED', 'FAILURE'].includes(upper)) return 'danger';
  return 'info';
}

watch(projectId, reload);
onMounted(async () => {
  await resources.refreshProjects();
  projectId.value = resources.projects[0]?.id ?? null;
  if (projectId.value !== null && projectId.value !== undefined) await reload();
});
</script>

<template>
  <div class="am-page governance-page" v-loading="loading">
    <PageHeader
      eyebrow="GOVERNANCE / SECURITY"
      title="治理与安全"
      description="团队、权限、项目额度、密钥、模型与审计记录统一治理。"
    >
      <el-select
        v-model="projectId"
        placeholder="选择项目"
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

    <template v-if="overview && selectedProject">
      <div class="am-metrics">
        <MetricCard label="你的角色" :value="roleLabel(overview.role)" />
        <MetricCard
          label="并发使用"
          :value="`${overview.usage.concurrentTasks} / ${overview.quota.concurrentTasks}`"
        />
        <MetricCard
          label="本月 Token"
          :value="overview.usage.tokenCount.toLocaleString()"
          :hint="`上限 ${overview.quota.monthlyTokenLimit.toLocaleString()}`"
        />
        <MetricCard
          label="本月成本"
          :value="`$${overview.usage.estimatedCost.toFixed(2)}`"
          :hint="`上限 $${overview.quota.monthlyCostLimit.toFixed(2)}`"
        />
      </div>

      <section class="am-card cost-section">
        <div class="section-title-row">
          <div>
            <h2>Runtime 成本分析</h2>
            <p>
              按当前项目聚合持久化的 Run Token 与模型成本；未知成本不会伪造成
              0。
            </p>
          </div>
          <el-progress
            type="dashboard"
            :percentage="usagePercent"
            :width="82"
            :stroke-width="8"
          />
        </div>
        <div class="cost-grid">
          <div>
            <span>Runs</span><b>{{ cost?.runCount ?? 0 }}</b>
          </div>
          <div>
            <span>Total Tokens</span><b>{{ cost?.totalTokens.toLocaleString() ?? 0 }}</b>
          </div>
          <div>
            <span>Estimated Cost</span><b>${{ (cost?.estimatedCost ?? 0).toFixed(4) }}</b>
          </div>
          <div>
            <span>成本未知 Runs</span><b>{{ cost?.unknownCostRuns ?? 0 }}</b>
          </div>
        </div>
      </section>

      <div class="governance-grid">
        <section class="am-card panel">
          <h2>团队协作</h2>
          <p>管理当前项目成员与角色。</p>
          <div class="member-list">
            <div
              v-for="member in overview.members"
              :key="member.userId"
              class="member-row"
            >
              <div class="member-avatar">
                {{
                  (member.displayName || member.email || String(member.userId))
                    .slice(0, 2)
                    .toUpperCase()
                }}
              </div>
              <div>
                <b>{{
                  member.displayName || member.email || `User ${member.userId}`
                }}</b><small>{{ roleLabel(member.role) }}</small>
              </div>
              <el-button
                v-if="member.role !== 'OWNER'"
                link
                type="danger"
                @click="removeMember(member.userId)"
              >
                移除
              </el-button>
            </div>
          </div>
          <div class="inline-form">
            <el-input v-model="memberEmail" placeholder="成员邮箱" /><el-select
              v-model="memberRole"
              style="width: 130px"
            >
              <el-option label="管理员" value="ADMIN" /><el-option
                label="开发成员"
                value="DEVELOPER"
              /><el-option label="只读成员" value="VIEWER" />
</el-select><el-button type="primary" @click="addMember">添加</el-button>
          </div>
        </section>
        <section class="am-card panel">
          <h2>项目额度</h2>
          <p>限制高频或高成本执行，避免意外消耗。</p>
          <div class="quota-grid">
            <el-form-item label="每分钟请求">
              <el-input-number
                v-model="overview.quota.requestsPerMinute"
                :min="1"
              />
</el-form-item><el-form-item label="并发任务">
              <el-input-number
                v-model="overview.quota.concurrentTasks"
                :min="1"
              />
</el-form-item><el-form-item label="月 Token">
              <el-input-number
                v-model="overview.quota.monthlyTokenLimit"
                :min="0"
                :step="100000"
              />
</el-form-item><el-form-item label="月成本">
              <el-input-number
                v-model="overview.quota.monthlyCostLimit"
                :min="0"
                :step="10"
              />
            </el-form-item>
          </div>
          <el-button type="primary" @click="saveQuota">保存额度</el-button>
        </section>
      </div>

      <div class="governance-grid">
        <section class="am-card panel">
          <div class="panel-head">
            <div>
              <h2>项目密钥</h2>
              <p>敏感值只在创建时提交，页面仅显示脱敏提示。</p>
            </div>
            <el-button @click="secretOpen = true">＋ 新建密钥</el-button>
          </div>
          <div v-if="overview.secrets.length" class="secret-list">
            <div v-for="secret in overview.secrets" :key="secret.id">
              <span>▤</span>
              <div>
                <b>{{ secret.name }}</b><small>{{ secret.kind }} · {{ secret.maskedHint }}</small>
              </div>
              <el-button link type="danger" @click="removeSecret(secret.id)">
                删除
              </el-button>
            </div>
          </div>
          <div v-else class="mini-empty">还没有项目密钥</div>
        </section>
        <section class="am-card panel">
          <h2>项目模型 Provider</h2>
          <p>仅作为项目回退模型；个人 BYOK 优先。</p>
          <el-form label-position="top" class="provider-form">
            <div class="provider-grid">
              <el-form-item label="Provider">
                <el-input v-model="providerForm.provider" />
</el-form-item><el-form-item label="Model">
                <el-input v-model="providerForm.modelName" />
              </el-form-item>
            </div>
            <el-form-item label="Base URL">
              <el-input v-model="providerForm.baseUrl" />
</el-form-item><el-form-item label="Secret">
              <el-select
                v-model="providerForm.secretId"
                clearable
                style="width: 100%"
              >
                <el-option
                  v-for="secret in overview.secrets"
                  :key="secret.id"
                  :label="`${secret.name} · ${secret.maskedHint}`"
                  :value="secret.id"
                />
              </el-select>
</el-form-item><el-checkbox v-model="providerForm.enabled">
              启用项目模型
            </el-checkbox>
</el-form><el-button
            type="primary"
            style="margin-top: 12px"
            @click="saveProvider"
          >
            保存模型配置
          </el-button>
        </section>
      </div>

      <div class="governance-grid">
        <section class="am-card panel">
          <h2>团队组织</h2>
          <p>将多个项目归入组织，统一协作边界。</p>
          <div class="inline-form">
            <el-input
              v-model="teamName"
              placeholder="新建团队工作空间"
            /><el-button type="primary" @click="createTeam">创建团队</el-button>
          </div>
          <div class="organization-list">
            <div v-for="org in organizations" :key="org.id" class="org-row">
              <div>
                <b>{{ org.name }}</b><small>Organization #{{ org.id }}</small>
              </div>
              <div>
                <el-button size="small" @click="bindProject(org.id)">
                  绑定当前项目
</el-button><el-button size="small" @click="addOrgMember(org.id)">
                  添加组织成员
                </el-button>
              </div>
            </div>
          </div>
          <div
            v-if="organizations.length"
            class="inline-form"
            style="margin-top: 8px"
          >
            <el-input
              v-model="orgMemberEmail"
              placeholder="组织成员邮箱"
            /><el-select v-model="orgRole" style="width: 130px">
              <el-option label="Member" value="MEMBER" /><el-option
                label="Admin"
                value="ADMIN"
              />
            </el-select>
          </div>
        </section>
        <section class="am-card panel">
          <h2>最近审计</h2>
          <p>项目级安全与配置操作记录。</p>
          <el-table :data="overview.audit.slice(0, 10)" size="small">
            <el-table-column
              prop="action"
              label="操作"
              min-width="150"
            /><el-table-column
              prop="resourceType"
              label="资源"
              width="110"
            /><el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="auditTone(row.result)">
                  {{ row.result }}
                </el-tag>
              </template>
</el-table-column><el-table-column label="时间" min-width="150">
              <template #default="{ row }">
                {{ new Date(row.createdAt).toLocaleString() }}
              </template>
            </el-table-column>
          </el-table>
        </section>
      </div>
    </template>

    <div v-else class="am-empty">
      <div>
        <strong>请选择一个项目</strong>
        <div style="margin-top: 6px">治理设置以 Project 为边界。</div>
      </div>
    </div>
  </div>

  <el-dialog v-model="secretOpen" title="新建项目密钥" width="500px">
    <el-form label-position="top">
      <el-form-item label="名称">
        <el-input v-model="secretForm.name" />
</el-form-item><el-form-item label="类型">
        <el-input v-model="secretForm.kind" />
</el-form-item><el-form-item label="值">
        <el-input v-model="secretForm.value" type="password" show-password />
      </el-form-item>
</el-form><template #footer>
      <el-button @click="secretOpen = false">取消</el-button><el-button type="primary" @click="addSecret">创建</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.cost-section {
  padding: 16px;
  margin-top: 16px;
}

.section-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title-row h2,
.panel h2 {
  margin: 0;
  font-size: 16px;
}

.section-title-row p,
.panel > p {
  margin: 4px 0 0;
  font-size: 10px;
  color: var(--am-muted);
}

.cost-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 12px;
  overflow: hidden;
  border: 1px solid var(--am-border);
  border-radius: 12px;
}

.cost-grid > div {
  padding: 14px;
  border-right: 1px solid var(--am-border);
}

.cost-grid > div:last-child {
  border-right: 0;
}

.cost-grid span,
.cost-grid b {
  display: block;
}

.cost-grid span {
  font-size: 9px;
  color: var(--am-muted);
}

.cost-grid b {
  margin-top: 5px;
  font-size: 18px;
}

.governance-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 14px;
}

.panel {
  padding: 16px;
}

.panel-head {
  display: flex;
  gap: 10px;
  justify-content: space-between;
}

.member-list {
  display: grid;
  gap: 6px;
  margin-top: 12px;
}

.member-row {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 8px;
  border: 1px solid var(--am-border);
  border-radius: 10px;
}

.member-avatar {
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

.member-row b,
.member-row small {
  display: block;
}

.member-row b {
  font-size: 10px;
}

.member-row small {
  margin-top: 2px;
  font-size: 8px;
  color: var(--am-muted);
}

.inline-form {
  display: flex;
  gap: 7px;
  margin-top: 12px;
}

.quota-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 10px;
  margin-top: 12px;
}

.secret-list {
  display: grid;
  gap: 6px;
  margin-top: 12px;
}

.secret-list > div {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 8px;
  border: 1px solid var(--am-border);
  border-radius: 10px;
}

.secret-list > div > span {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  color: var(--am-primary);
  background: var(--am-primary-soft);
  border-radius: 9px;
}

.secret-list b,
.secret-list small {
  display: block;
}

.secret-list b {
  font-size: 10px;
}

.secret-list small {
  margin-top: 2px;
  font-size: 8px;
  color: var(--am-muted);
}

.mini-empty {
  padding: 18px;
  margin-top: 12px;
  font-size: 10px;
  color: var(--am-muted);
  text-align: center;
  border: 1px dashed var(--am-border);
  border-radius: 10px;
}

.provider-form {
  margin-top: 12px;
}

.provider-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.organization-list {
  display: grid;
  gap: 6px;
  margin-top: 12px;
}

.org-row {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  padding: 9px;
  border: 1px solid var(--am-border);
  border-radius: 10px;
}

.org-row b,
.org-row small {
  display: block;
}

.org-row b {
  font-size: 10px;
}

.org-row small {
  margin-top: 2px;
  font-size: 8px;
  color: var(--am-muted);
}

@media (max-width: 1000px) {
  .governance-grid {
    grid-template-columns: 1fr;
  }

  .cost-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .cost-grid > div:nth-child(2) {
    border-right: 0;
  }

  .cost-grid > div:nth-child(-n + 2) {
    border-bottom: 1px solid var(--am-border);
  }
}

@media (max-width: 620px) {
  .inline-form {
    flex-direction: column;
  }

  .quota-grid,
  .provider-grid {
    grid-template-columns: 1fr;
  }

  .cost-grid {
    grid-template-columns: 1fr;
  }

  .cost-grid > div {
    border-right: 0;
    border-bottom: 1px solid var(--am-border);
  }

  .cost-grid > div:last-child {
    border-bottom: 0;
  }
}
</style>
