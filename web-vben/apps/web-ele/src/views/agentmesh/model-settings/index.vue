<script setup lang="ts">
import type { UserModelService, UserModelServiceInput } from '#/api/agentmesh';

import { computed, onMounted, reactive, ref } from 'vue';

import { ElMessage, ElMessageBox } from 'element-plus';

import {
  createUserModelService,
  deleteUserModelService,
  friendlyApiError,
  listUserModelServices,
  updateUserModelService,
} from '#/api/agentmesh';
import MetricCard from '#/components/agentmesh/MetricCard.vue';
import PageHeader from '#/components/agentmesh/PageHeader.vue';

const services = ref<UserModelService[]>([]);
const dialogOpen = ref(false);
const editingId = ref<null | number>(null);
const form = reactive<UserModelServiceInput>({
  name: '我的模型服务',
  provider: 'qwen',
  baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  modelName: 'qwen-plus',
  visionModelName: 'qwen-vl-plus',
  apiKey: '',
  enabled: true,
  autoRoute: true,
  isDefault: true,
});

const enabledCount = computed(
  () => services.value.filter((item) => item.enabled).length,
);
const autoRouteCount = computed(
  () => services.value.filter((item) => item.enabled && item.autoRoute).length,
);
const defaultService = computed(
  () => services.value.find((item) => item.isDefault) ?? null,
);

async function reload() {
  services.value = await listUserModelServices();
}
function resetForm() {
  Object.assign(form, {
    name: '我的模型服务',
    provider: 'qwen',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    modelName: 'qwen-plus',
    visionModelName: 'qwen-vl-plus',
    apiKey: '',
    enabled: true,
    autoRoute: true,
    isDefault: services.value.length === 0,
  });
  editingId.value = null;
}
function openCreate(preset?: 'custom' | 'openai' | 'qwen') {
  resetForm();
  if (preset) applyPreset(preset);
  dialogOpen.value = true;
}
function openEdit(service: UserModelService) {
  editingId.value = service.id;
  Object.assign(form, {
    name: service.name,
    provider: service.provider,
    baseUrl: service.baseUrl,
    modelName: service.modelName,
    visionModelName: service.visionModelName,
    apiKey: '',
    enabled: service.enabled,
    autoRoute: service.autoRoute,
    isDefault: service.isDefault,
  });
  dialogOpen.value = true;
}
function applyPreset(preset: 'custom' | 'openai' | 'qwen') {
  if (preset === 'qwen')
    Object.assign(form, {
      provider: 'qwen',
      baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      modelName: 'qwen-plus',
      visionModelName: 'qwen-vl-plus',
    });
  if (preset === 'openai')
    Object.assign(form, {
      provider: 'openai-compatible',
      baseUrl: 'https://api.openai.com/v1',
      modelName: 'gpt-5.6',
      visionModelName: 'gpt-5.6',
    });
  if (preset === 'custom')
    Object.assign(form, {
      provider: 'openai-compatible',
      baseUrl: '',
      modelName: '',
      visionModelName: '',
    });
}
async function save() {
  try {
    await (editingId.value
      ? updateUserModelService(editingId.value, form)
      : createUserModelService(form));
    dialogOpen.value = false;
    await reload();
    ElMessage.success('模型服务已保存');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '保存失败'));
  }
}
async function remove(service: UserModelService) {
  await ElMessageBox.confirm(
    `删除模型服务“${service.name}”？`,
    '删除模型服务',
    { type: 'warning' },
  );
  try {
    await deleteUserModelService(service.id);
    await reload();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '删除失败'));
  }
}
async function toggle(service: UserModelService, enabled: boolean) {
  try {
    await updateUserModelService(service.id, {
      name: service.name,
      provider: service.provider,
      baseUrl: service.baseUrl,
      modelName: service.modelName,
      visionModelName: service.visionModelName,
      apiKey: '',
      enabled,
      autoRoute: service.autoRoute,
      isDefault: service.isDefault,
    });
    await reload();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '更新失败'));
  }
}

onMounted(reload);
</script>

<template>
  <div class="am-page model-page">
    <PageHeader
      eyebrow="BYOK / MODEL ROUTING"
      title="模型设置"
      description="保存多个个人模型服务，默认由 AgentMesh 自动选择，也可以在工作台为单次任务手动指定。"
    >
      <el-button type="primary" @click="openCreate">＋ 添加模型服务</el-button>
    </PageHeader>
    <div class="am-metrics">
      <MetricCard label="模型服务" :value="services.length" /><MetricCard
        label="当前可用"
        :value="enabledCount"
        tone="success"
      /><MetricCard
        label="参与自动路由"
        :value="autoRouteCount"
        tone="primary"
      /><MetricCard
        label="默认服务"
        :value="defaultService?.modelName || '未设置'"
      />
    </div>

    <section class="am-card service-section">
      <div class="section-head">
        <div>
          <h2>我的模型服务</h2>
          <p>API Key 仅在提交时发送给服务端加密保存；浏览器只显示脱敏提示。</p>
        </div>
        <el-button type="primary" @click="openCreate">
          ＋ 添加模型服务
        </el-button>
      </div>
      <div v-if="services.length" class="service-list">
        <article
          v-for="service in services"
          :key="service.id"
          class="service-row"
        >
          <div class="service-icon">▤</div>
          <div class="service-copy">
            <div class="service-title">
              <b>{{ service.name }}</b><el-tag v-if="service.isDefault" size="small" round>默认</el-tag><el-tag
                v-if="service.autoRoute"
                size="small"
                round
                effect="plain"
              >
                自动路由
              </el-tag>
            </div>
            <div class="service-meta">
              {{ service.modelName }} · {{ service.provider }} ·
              {{ service.maskedHint }}
            </div>
            <div class="service-url">{{ service.baseUrl }}</div>
          </div>
          <div class="service-actions">
            <span :class="service.enabled ? 'am-success' : 'am-muted'">● {{ service.enabled ? '已启用' : '已停用' }}</span><el-switch
              :model-value="service.enabled"
              @change="toggle(service, Boolean($event))"
            /><el-button @click="openEdit(service)">编辑</el-button><el-button type="danger" plain @click="remove(service)">
              删除
            </el-button>
          </div>
        </article>
      </div>
      <div v-else class="empty-model">
        <div>▤</div>
        <h3>还没有模型服务</h3>
        <p>添加通义千问、OpenAI 或任意 OpenAI 兼容接口后即可运行任务。</p>
        <div>
          <el-button @click="openCreate('qwen')">通义千问</el-button><el-button @click="openCreate('openai')">OpenAI</el-button><el-button type="primary" @click="openCreate">
            添加第一个模型服务
          </el-button>
        </div>
      </div>
    </section>

    <section class="am-card routing-section">
      <h2>调用规则</h2>
      <div class="rule-grid">
        <div>
          <b>自动选择</b>
          <p>
            默认从已启用且加入自动路由的个人模型中，根据质量、成本、延迟和历史成功率选择。
          </p>
        </div>
        <div>
          <b>手动指定</b>
          <p>
            工作台可以为当前任务指定一个模型服务；显式选择优先，但仍通过
            BYOK、权限和可用性检查。
          </p>
        </div>
        <div>
          <b>项目回退</b>
          <p>
            没有可用个人模型时，才允许回退到项目管理员显式配置的项目级模型。
          </p>
        </div>
      </div>
    </section>
  </div>

  <el-dialog
    v-model="dialogOpen"
    :title="editingId ? '编辑模型服务' : '添加模型服务'"
    width="600px"
  >
    <div class="preset-row">
      <el-button @click="applyPreset('qwen')">通义千问</el-button><el-button @click="applyPreset('openai')">OpenAI</el-button><el-button @click="applyPreset('custom')">自定义兼容接口</el-button>
    </div>
    <el-form label-position="top" style="margin-top: 14px">
      <el-form-item label="服务名称">
        <el-input v-model="form.name" />
</el-form-item><el-form-item label="Provider">
        <el-input v-model="form.provider" />
</el-form-item><el-form-item label="Base URL">
        <el-input v-model="form.baseUrl" />
      </el-form-item>
      <div class="form-grid">
        <el-form-item label="文本模型">
          <el-input v-model="form.modelName" />
</el-form-item><el-form-item label="视觉模型">
          <el-input v-model="form.visionModelName" />
        </el-form-item>
      </div>
      <el-form-item
        :label="editingId ? 'API Key（留空表示不修改）' : 'API Key'"
      >
        <el-input v-model="form.apiKey" type="password" show-password />
      </el-form-item>
      <div class="check-row">
        <el-checkbox v-model="form.enabled">启用</el-checkbox><el-checkbox v-model="form.autoRoute">参与自动路由</el-checkbox><el-checkbox v-model="form.isDefault">设为默认</el-checkbox>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="dialogOpen = false">取消</el-button><el-button type="primary" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.service-section,
.routing-section {
  padding: 18px;
  margin-top: 16px;
}

.section-head {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  justify-content: space-between;
}

.section-head h2,
.routing-section h2 {
  margin: 0;
  font-size: 18px;
}

.section-head p {
  margin: 5px 0 0;
  font-size: 11px;
  color: var(--am-muted);
}

.service-list {
  display: grid;
  gap: 9px;
  margin-top: 15px;
}

.service-row {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 13px;
  border: 1px solid var(--am-border);
  border-radius: 12px;
}

.service-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  font-weight: 800;
  color: var(--am-primary);
  background: var(--am-primary-soft);
  border-radius: 11px;
}

.service-title {
  display: flex;
  gap: 6px;
  align-items: center;
}

.service-title b {
  font-size: 12px;
}

.service-meta {
  margin-top: 4px;
  font-size: 10px;
  color: #687083;
}

.service-url {
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 9px;
  color: var(--am-muted);
  white-space: nowrap;
}

.service-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 9px;
}

.empty-model {
  display: grid;
  place-items: center;
  align-content: center;
  min-height: 240px;
  text-align: center;
}

.empty-model > div:first-child {
  font-size: 32px;
  color: var(--am-primary);
}

.empty-model h3 {
  margin: 10px 0 4px;
}

.empty-model p {
  margin: 0 0 14px;
  font-size: 11px;
  color: var(--am-muted);
}

.rule-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.rule-grid > div {
  padding: 14px;
  background: #fbfaff;
  border: 1px solid var(--am-border);
  border-radius: 12px;
}

.rule-grid b {
  font-size: 12px;
}

.rule-grid p {
  margin: 5px 0 0;
  font-size: 10px;
  line-height: 1.7;
  color: var(--am-muted);
}

.preset-row {
  display: flex;
  gap: 8px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.check-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

@media (max-width: 900px) {
  .service-row {
    grid-template-columns: 44px minmax(0, 1fr);
  }

  .service-actions {
    grid-column: 1/-1;
    justify-content: flex-end;
  }

  .rule-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .section-head {
    flex-direction: column;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
