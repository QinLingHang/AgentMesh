<script setup lang="ts">
import type { MemoryCategory, UserMemory } from '#/api/agentmesh';

import { computed, onMounted, reactive, ref } from 'vue';

import { ElMessage, ElMessageBox } from 'element-plus';

import {
  createMemory,
  deleteMemory,
  friendlyApiError,
  listMemories,
  updateMemory,
} from '#/api/agentmesh';
import EmptyState from '#/components/agentmesh/EmptyState.vue';
import MetricCard from '#/components/agentmesh/MetricCard.vue';
import PageHeader from '#/components/agentmesh/PageHeader.vue';
import StatusBadge from '#/components/agentmesh/StatusBadge.vue';

const rows = ref<UserMemory[]>([]);
const query = ref('');
const category = ref<'' | MemoryCategory>('');
const status = ref('');
const dialogOpen = ref(false);
const editingId = ref<null | number>(null);
const busy = ref(false);
const form = reactive({
  category: 'fact' as MemoryCategory,
  memoryKey: '',
  content: '',
  confidence: 1,
  status: 'ACTIVE',
});
const categories: Array<{ label: string; value: MemoryCategory }> = [
  { label: '偏好', value: 'preference' },
  { label: '个人资料', value: 'profile' },
  { label: '目标', value: 'goal' },
  { label: '工作流', value: 'workflow' },
  { label: '事实', value: 'fact' },
  { label: '其他', value: 'other' },
];
const filtered = computed(() =>
  rows.value.filter((row) => {
    const keyword = query.value.trim().toLowerCase();
    return (
      (!category.value || row.category === category.value) &&
      (!status.value || row.status === status.value) &&
      (!keyword ||
        `${row.memoryKey} ${row.content}`.toLowerCase().includes(keyword))
    );
  }),
);
const activeCount = computed(
  () =>
    rows.value.filter((row) => row.status.toUpperCase() === 'ACTIVE').length,
);
const manualCount = computed(
  () => rows.value.filter((row) => row.sourceType === 'manual').length,
);
const inferredCount = computed(
  () => rows.value.filter((row) => row.sourceType === 'inferred_user').length,
);

async function reload() {
  try {
    rows.value = await listMemories({ limit: 500 });
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '读取长期记忆失败'));
  }
}
function openCreate() {
  editingId.value = null;
  Object.assign(form, {
    category: 'fact',
    memoryKey: '',
    content: '',
    confidence: 1,
    status: 'ACTIVE',
  });
  dialogOpen.value = true;
}
function openEdit(row: UserMemory) {
  editingId.value = row.id;
  Object.assign(form, {
    category: row.category,
    memoryKey: row.memoryKey,
    content: row.content,
    confidence: row.confidence,
    status: row.status,
  });
  dialogOpen.value = true;
}
async function save() {
  if (!form.memoryKey.trim() || !form.content.trim())
    return ElMessage.warning('记忆标识和内容不能为空');
  busy.value = true;
  try {
    await (editingId.value === null || editingId.value === undefined
      ? createMemory({
          category: form.category,
          memoryKey: form.memoryKey.trim(),
          content: form.content.trim(),
          sourceType: 'manual',
          confidence: form.confidence,
          status: form.status,
        })
      : updateMemory(editingId.value, {
          category: form.category,
          memoryKey: form.memoryKey.trim(),
          content: form.content.trim(),
          sourceType: 'manual',
          confidence: form.confidence,
          status: form.status,
        }));
    dialogOpen.value = false;
    await reload();
    ElMessage.success(
      editingId.value === null || editingId.value === undefined
        ? '长期记忆已创建'
        : '长期记忆已更新',
    );
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '保存长期记忆失败'));
  } finally {
    busy.value = false;
  }
}
async function remove(row: UserMemory) {
  await ElMessageBox.confirm(
    `删除长期记忆“${row.memoryKey}”？删除后 AgentMesh 将不再召回它。`,
    '删除长期记忆',
    { type: 'warning' },
  );
  try {
    await deleteMemory(row.id);
    await reload();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '删除长期记忆失败'));
  }
}
onMounted(reload);
</script>

<template>
  <div class="am-page memory-page">
    <PageHeader
      eyebrow="USER-GLOBAL MEMORY"
      title="长期记忆"
      description="管理当前用户跨普通会话和不同项目共享的长期记忆；项目知识与检索证据不属于长期记忆。"
    >
      <el-button type="primary" @click="openCreate">＋ 新增记忆</el-button>
    </PageHeader>
    <div class="am-metrics">
      <MetricCard
        label="全部记忆"
        :value="rows.length"
        hint="当前用户长期记忆"
      />
      <MetricCard label="有效记忆" :value="activeCount" tone="success" />
      <MetricCard label="手动维护" :value="manualCount" tone="primary" />
      <MetricCard label="自动推断" :value="inferredCount" />
    </div>
    <section class="am-card memory-card">
      <div class="memory-filter">
        <el-input
          v-model="query"
          clearable
          placeholder="搜索 key 或记忆内容"
        /><el-select
          v-model="category"
          clearable
          placeholder="全部类别"
          style="width: 150px"
        >
          <el-option
            v-for="item in categories"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
</el-select><el-select
          v-model="status"
          clearable
          placeholder="全部状态"
          style="width: 140px"
        >
          <el-option label="ACTIVE" value="ACTIVE" /><el-option
            label="DISABLED"
            value="DISABLED"
          />
        </el-select>
      </div>
      <el-table v-if="filtered.length" :data="filtered" row-key="id">
        <el-table-column prop="memoryKey" label="记忆标识" min-width="170" />
        <el-table-column
          prop="content"
          label="记忆内容"
          min-width="320"
          show-overflow-tooltip
        />
        <el-table-column prop="category" label="类别" width="110" />
        <el-table-column prop="sourceType" label="来源" width="120" />
        <el-table-column label="置信度" width="100">
          <template #default="{ row }">
            {{ Math.round(row.confidence * 100) }}%
          </template>
        </el-table-column>
        <el-table-column label="状态" width="105">
          <template #default="{ row }">
            <StatusBadge :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">
              编辑
</el-button><el-button link type="danger" @click="remove(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <EmptyState
        v-else
        title="还没有长期记忆"
        description="你可以手动新增；Runtime 也会按治理规则写入用户长期记忆。"
      >
        <el-button type="primary" @click="openCreate">
          新增第一条记忆
        </el-button>
      </EmptyState>
    </section>
  </div>

  <el-dialog
    v-model="dialogOpen"
    :title="
      editingId === null || editingId === undefined
        ? '新增长期记忆'
        : '编辑长期记忆'
    "
    width="560px"
  >
    <el-form label-position="top">
      <el-form-item label="类别">
        <el-select v-model="form.category" style="width: 100%">
          <el-option
            v-for="item in categories"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
</el-form-item><el-form-item label="记忆标识">
        <el-input
          v-model="form.memoryKey"
          placeholder="例如 preferred_language"
        />
</el-form-item><el-form-item label="记忆内容">
        <el-input
          v-model="form.content"
          type="textarea"
          :rows="5"
        />
</el-form-item><el-form-item label="置信度">
        <el-slider
          v-model="form.confidence"
          :min="0"
          :max="1"
          :step="0.05"
          show-input
        />
</el-form-item><el-form-item label="状态">
        <el-radio-group v-model="form.status">
          <el-radio-button label="ACTIVE">ACTIVE</el-radio-button><el-radio-button label="DISABLED"> DISABLED </el-radio-button>
        </el-radio-group>
      </el-form-item>
    </el-form>
    <div class="memory-boundary">
      这里只管理用户长期记忆。项目文档、RAG 检索证据、Tool/MCP
      结果不会被当作长期记忆在这里保存。
    </div>
    <template #footer>
      <el-button @click="dialogOpen = false">取消</el-button><el-button type="primary" :loading="busy" @click="save">
        保存
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.memory-card {
  padding: 15px;
  margin-top: 15px;
}

.memory-filter {
  display: flex;
  gap: 8px;
  margin-bottom: 13px;
}

.memory-boundary {
  padding: 10px;
  font-size: 10px;
  line-height: 1.6;
  color: #665d87;
  background: var(--am-primary-soft);
  border-radius: 10px;
}

@media (max-width: 700px) {
  .memory-filter {
    flex-direction: column;
  }

  .memory-filter :deep(.el-select) {
    width: 100% !important;
  }
}
</style>
