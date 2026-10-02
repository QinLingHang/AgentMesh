<script setup lang="ts">
import type { KnowledgeBase, KnowledgeFile } from '#/api/agentmesh';

import { computed, onMounted, ref } from 'vue';

import { ElMessage, ElMessageBox } from 'element-plus';

import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  deleteKnowledgeBaseFile,
  friendlyApiError,
  listKnowledgeBases,
  listKnowledgeFiles,
  reindexKnowledgeFile,
  updateKnowledgeBase,
  uploadKnowledgeBaseFile,
} from '#/api/agentmesh';
import EmptyState from '#/components/agentmesh/EmptyState.vue';
import MetricCard from '#/components/agentmesh/MetricCard.vue';
import PageHeader from '#/components/agentmesh/PageHeader.vue';
import StatusBadge from '#/components/agentmesh/StatusBadge.vue';
import { useAgentMeshResourcesStore } from '#/store/agentmesh-resources';

const resources = useAgentMeshResourcesStore();
const bases = ref<KnowledgeBase[]>([]);
const files = ref<KnowledgeFile[]>([]);
const activeBaseId = ref<'all' | number>('all');
const query = ref('');
const statusFilter = ref('ALL');
const createOpen = ref(false);
const uploadInput = ref<HTMLInputElement | null>(null);
const newName = ref('知识库');
const newDescription = ref('');
const newScope = ref<'GLOBAL' | 'PROJECT'>('GLOBAL');
const newProjectId = ref<null | number>(null);
const editingBaseId = ref<null | number>(null);
const busy = ref(false);

const filteredFiles = computed(() =>
  files.value.filter((file) => {
    const matchBase =
      activeBaseId.value === 'all' ||
      file.knowledgeBaseId === activeBaseId.value;
    const matchStatus =
      statusFilter.value === 'ALL' || file.status === statusFilter.value;
    const keyword = query.value.trim().toLowerCase();
    const matchQuery =
      !keyword ||
      [
        file.originalName,
        file.knowledgeBaseName,
        file.projectName ?? '',
        file.extension,
      ]
        .join(' ')
        .toLowerCase()
        .includes(keyword);
    return matchBase && matchStatus && matchQuery;
  }),
);
const ready = computed(
  () => files.value.filter((item) => item.status === 'READY').length,
);
const pending = computed(
  () =>
    files.value.filter((item) => ['INDEXING', 'UPLOADED'].includes(item.status))
      .length,
);
const failed = computed(
  () => files.value.filter((item) => item.status === 'ERROR').length,
);
const selectedBase = computed(() =>
  activeBaseId.value === 'all'
    ? null
    : (bases.value.find((item) => item.id === activeBaseId.value) ?? null),
);

async function reload() {
  const [baseRows, fileRows] = await Promise.all([
    listKnowledgeBases(),
    listKnowledgeFiles(),
    resources.refreshProjects(),
  ]);
  bases.value = baseRows;
  files.value = fileRows;
}
function openCreateBase() {
  editingBaseId.value = null;
  newName.value = '知识库';
  newDescription.value = '';
  newScope.value = 'GLOBAL';
  newProjectId.value = null;
  createOpen.value = true;
}
function openEditBase(base: KnowledgeBase) {
  editingBaseId.value = base.id;
  newName.value = base.name;
  newDescription.value = base.description ?? '';
  newScope.value = base.scope;
  newProjectId.value = base.projectId ?? null;
  createOpen.value = true;
}
async function createBase() {
  if (!newName.value.trim()) return ElMessage.warning('请输入知识库名称');
  if (
    (editingBaseId.value === null || editingBaseId.value === undefined) &&
    newScope.value === 'PROJECT' &&
    (newProjectId.value === null || newProjectId.value === undefined)
  )
    return ElMessage.warning('项目知识库必须选择项目');
  busy.value = true;
  try {
    if (editingBaseId.value === null || editingBaseId.value === undefined) {
      const created = await createKnowledgeBase(
        newName.value.trim(),
        newDescription.value.trim(),
        newScope.value,
        newScope.value === 'PROJECT' ? newProjectId.value : null,
      );
      activeBaseId.value = created.id;
      ElMessage.success('知识库已创建');
    } else {
      await updateKnowledgeBase(
        editingBaseId.value,
        newName.value.trim(),
        newDescription.value.trim(),
      );
      ElMessage.success('知识库已更新');
    }
    createOpen.value = false;
    await reload();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '保存失败'));
  } finally {
    busy.value = false;
  }
}
async function removeBase(base: KnowledgeBase) {
  await ElMessageBox.confirm(`删除知识库“${base.name}”？`, '删除知识库', {
    type: 'warning',
  });
  try {
    await deleteKnowledgeBase(base.id);
    if (activeBaseId.value === base.id) activeBaseId.value = 'all';
    await reload();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '删除失败'));
  }
}
async function upload(event: Event) {
  const target = event.target as HTMLInputElement;
  const selected =
    selectedBase.value ??
    bases.value.find((item) => item.isDefault) ??
    bases.value[0];
  if (!selected) {
    ElMessage.warning('请先创建一个知识库');
    target.value = '';
    return;
  }
  const filesToUpload = [...(target.files ?? [])];
  if (filesToUpload.length === 0) return;
  busy.value = true;
  try {
    for (const file of filesToUpload)
      await uploadKnowledgeBaseFile(selected.id, file);
    await reload();
    ElMessage.success('文件已上传并进入索引流程');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '上传失败'));
  } finally {
    busy.value = false;
    target.value = '';
  }
}
async function reindex(file: KnowledgeFile) {
  try {
    await reindexKnowledgeFile(file.id);
    await reload();
    ElMessage.success('已重新提交索引');
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '重建索引失败'));
  }
}
async function removeFile(file: KnowledgeFile) {
  await ElMessageBox.confirm(`删除“${file.originalName}”？`, '删除文件', {
    type: 'warning',
  });
  try {
    await deleteKnowledgeBaseFile(file.knowledgeBaseId, file.id);
    await reload();
  } catch (error) {
    ElMessage.error(friendlyApiError(error, '删除失败'));
  }
}
function bytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

onMounted(reload);
</script>

<template>
  <div class="am-page knowledge-page">
    <PageHeader
      eyebrow="KNOWLEDGE / RAG"
      title="知识库"
      description="管理知识集合、文件索引、处理状态与检索范围。"
    >
      <input ref="uploadInput" hidden type="file" multiple @change="upload" />
      <el-button @click="openCreateBase">＋ 新建知识库</el-button><el-button type="primary" :loading="busy" @click="uploadInput?.click()">
        ＋ 上传知识
      </el-button>
    </PageHeader>

    <div class="knowledge-layout">
      <aside class="knowledge-tree am-card">
        <div class="tree-head">
          <span>知识集合</span><button @click="openCreateBase">＋</button>
        </div>
        <button
          class="tree-row"
          :class="{ active: activeBaseId === 'all' }"
          @click="activeBaseId = 'all'"
        >
          <span>▤ 全部文档</span><b>{{ files.length }}</b>
        </button>
        <div class="tree-section">全局知识</div>
        <div
          v-for="base in bases.filter((item) => item.scope === 'GLOBAL')"
          :key="base.id"
          class="base-wrap"
        >
          <button
            class="tree-row"
            :class="{ active: activeBaseId === base.id }"
            @click="activeBaseId = base.id"
          >
            <span>▣ {{ base.name }}</span><b>{{ base.fileCount }}</b>
</button><button class="base-delete" @click.stop="removeBase(base)">×</button>
        </div>
        <div class="tree-section">项目知识</div>
        <div
          v-for="base in bases.filter((item) => item.scope === 'PROJECT')"
          :key="base.id"
          class="base-wrap"
        >
          <button
            class="tree-row"
            :class="{ active: activeBaseId === base.id }"
            @click="activeBaseId = base.id"
          >
            <span>◫ {{ base.name }}</span><b>{{ base.fileCount }}</b>
</button><button class="base-delete" @click.stop="removeBase(base)">×</button>
        </div>
      </aside>

      <main class="knowledge-main">
        <div class="am-metrics">
          <MetricCard
            label="全部文件"
            :value="files.length"
            hint="已加入的资料"
          />
          <MetricCard
            label="已索引"
            :value="ready"
            tone="success"
            hint="可用于检索"
          />
          <MetricCard
            label="处理中"
            :value="pending"
            tone="primary"
            hint="上传 / 索引中"
          />
          <MetricCard
            label="失败"
            :value="failed"
            tone="danger"
            hint="需要处理"
          />
        </div>
        <section class="am-card files-card">
          <div class="files-head">
            <div>
              <h3>{{ selectedBase?.name || '全部知识文件' }}</h3>
              <p>
                {{
                  selectedBase?.description ||
                  '跨全局和项目知识库查看真实索引状态。'
                }}
              </p>
            </div>
            <span>{{ filteredFiles.length }} / {{ files.length }}</span>
          </div>
          <div class="filter-row">
            <el-input
              v-model="query"
              clearable
              placeholder="搜索文件、知识库或项目…"
            /><el-select v-model="statusFilter" style="width: 150px">
              <el-option label="全部状态" value="ALL" /><el-option
                label="已索引"
                value="READY"
              /><el-option label="索引中" value="INDEXING" /><el-option
                label="已上传"
                value="UPLOADED"
              /><el-option label="错误" value="ERROR" />
            </el-select>
          </div>
          <el-table
            v-if="filteredFiles.length"
            :data="filteredFiles"
            style="width: 100%"
            row-key="id"
          >
            <el-table-column label="文件" min-width="230">
              <template #default="{ row }">
                <div class="file-name">
                  <span>▤</span>
                  <div>
                    <b>{{ row.originalName }}</b><small>{{ row.extension.toUpperCase() }} ·
                      {{ bytes(row.sizeBytes) }}</small>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column
              prop="knowledgeBaseName"
              label="知识库"
              min-width="130"
            />
            <el-table-column label="范围" width="100">
              <template #default="{ row }">
                {{
                  row.scope === 'GLOBAL' ? '全局' : row.projectName || '项目'
                }}
              </template>
            </el-table-column>
            <el-table-column prop="chunkCount" label="Chunks" width="90" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <StatusBadge :status="row.status" />
              </template>
            </el-table-column>
            <el-table-column label="更新时间" min-width="150">
              <template #default="{ row }">
                {{ new Date(row.updatedAt).toLocaleString() }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="reindex(row)">
                  重建索引
</el-button><el-button link type="danger" @click="removeFile(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <EmptyState
            v-else
            title="当前范围还没有知识文件"
            description="上传文件后，AgentMesh 会在索引完成后自动参与检索。"
          >
            <el-button type="primary" @click="uploadInput?.click()">
              上传知识
            </el-button>
          </EmptyState>
        </section>
      </main>

      <aside class="knowledge-side">
        <section class="am-card side-card">
          <div class="side-title">检索准备度</div>
          <div class="readiness">
            <strong>{{
                files.length ? Math.round((ready / files.length) * 100) : 0
              }}%</strong><span>已索引文件占比</span>
          </div>
          <el-progress
            :percentage="
              files.length ? Math.round((ready / files.length) * 100) : 0
            "
            :stroke-width="8"
            :show-text="false"
          />
        </section>
        <section class="am-card side-card">
          <div class="side-title">索引概览</div>
          <div class="side-row">
            <span>总 Chunks</span><b>{{ files.reduce((sum, item) => sum + item.chunkCount, 0) }}</b>
          </div>
          <div class="side-row">
            <span>文本 Chunk</span><b>{{
              files.reduce((sum, item) => sum + item.textChunkCount, 0)
            }}</b>
          </div>
          <div class="side-row">
            <span>视觉证据</span><b>{{
              files.reduce((sum, item) => sum + item.visualEvidenceCount, 0)
            }}</b>
          </div>
          <div class="side-row">
            <span>总页数</span><b>{{ files.reduce((sum, item) => sum + item.pageCount, 0) }}</b>
          </div>
        </section>
        <section v-if="selectedBase" class="am-card side-card">
          <div class="side-title">当前知识库</div>
          <h3>{{ selectedBase.name }}</h3>
          <p>{{ selectedBase.description || '没有描述' }}</p>
          <div class="side-row">
            <span>范围</span><b>{{ selectedBase.scope }}</b>
          </div>
          <div class="side-row">
            <span>文件</span><b>{{ selectedBase.fileCount }}</b>
          </div>
          <el-button
            style="width: 100%; margin-top: 10px"
            @click="openEditBase(selectedBase)"
          >
            编辑知识库
          </el-button>
        </section>
      </aside>
    </div>
  </div>

  <el-dialog
    v-model="createOpen"
    :title="
      editingBaseId === null || editingBaseId === undefined
        ? '新建知识库'
        : '编辑知识库'
    "
    width="500px"
  >
    <el-form label-position="top">
      <el-form-item label="名称"><el-input v-model="newName" /></el-form-item><el-form-item label="描述">
        <el-input
          v-model="newDescription"
          type="textarea"
          :rows="3"
        />
</el-form-item><el-form-item
        v-if="editingBaseId === null || editingBaseId === undefined"
        label="范围"
      >
        <el-radio-group v-model="newScope">
          <el-radio-button label="GLOBAL">全局</el-radio-button><el-radio-button label="PROJECT"> 项目 </el-radio-button>
        </el-radio-group>
</el-form-item><el-form-item
        v-if="
          (editingBaseId === null || editingBaseId === undefined) &&
          newScope === 'PROJECT'
        "
        label="所属项目"
      >
        <el-select
          v-model="newProjectId"
          placeholder="选择项目"
          style="width: 100%"
        >
          <el-option
            v-for="project in resources.projects"
            :key="project.id"
            :label="project.name"
            :value="project.id"
          />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="createOpen = false">取消</el-button><el-button type="primary" :loading="busy" @click="createBase">
        {{
          editingBaseId === null || editingBaseId === undefined
            ? '创建'
            : '保存'
        }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.knowledge-layout {
  display: grid;
  grid-template-columns: 205px minmax(0, 1fr) 250px;
  gap: 16px;
}

.knowledge-tree {
  align-self: start;
  padding: 12px;
  box-shadow: none;
}

.tree-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 3px 7px 10px;
  font-size: 11px;
  font-weight: 800;
}

.tree-head button,
.base-delete {
  color: var(--am-primary);
  cursor: pointer;
  background: transparent;
  border: 0;
}

.tree-row {
  display: flex;
  gap: 8px;
  justify-content: space-between;
  width: 100%;
  padding: 9px;
  font-size: 10px;
  color: #61697a;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 9px;
}

.tree-row.active,
.tree-row:hover {
  color: var(--am-primary);
  background: var(--am-primary-soft);
}

.tree-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-section {
  padding: 13px 8px 5px;
  font-size: 9px;
  font-weight: 800;
  color: var(--am-muted);
}

.base-wrap {
  position: relative;
}

.base-delete {
  position: absolute;
  top: 5px;
  right: 4px;
  display: none;
}

.base-wrap:hover .base-delete {
  display: block;
}

.base-wrap:hover .tree-row b {
  opacity: 0;
}

.knowledge-main {
  min-width: 0;
}

.files-card {
  padding: 14px;
  margin-top: 14px;
}

.files-head {
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.files-head h3 {
  margin: 0;
  font-size: 16px;
}

.files-head p {
  margin: 4px 0 0;
  font-size: 10px;
  color: var(--am-muted);
}

.files-head > span {
  font-size: 10px;
  color: var(--am-muted);
}

.filter-row {
  display: flex;
  gap: 8px;
  margin: 13px 0;
}

.file-name {
  display: flex;
  gap: 9px;
  align-items: center;
}

.file-name > span {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  color: var(--am-primary);
  background: var(--am-primary-soft);
  border-radius: 9px;
}

.file-name b,
.file-name small {
  display: block;
}

.file-name small {
  margin-top: 2px;
  font-size: 9px;
  color: var(--am-muted);
}

.knowledge-side {
  display: grid;
  gap: 12px;
  align-content: start;
}

.side-card {
  padding: 14px;
}

.side-title {
  margin-bottom: 10px;
  font-size: 10px;
  font-weight: 800;
  color: #666d7d;
}

.readiness {
  display: flex;
  align-items: end;
  justify-content: space-between;
  margin-bottom: 10px;
}

.readiness strong {
  font-size: 27px;
}

.readiness span {
  font-size: 9px;
  color: var(--am-muted);
}

.side-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  font-size: 10px;
  border-bottom: 1px solid var(--am-border);
}

.side-row:last-child {
  border-bottom: 0;
}

.side-row span {
  color: var(--am-muted);
}

.side-card h3 {
  margin: 4px 0;
}

.side-card p {
  font-size: 10px;
  line-height: 1.6;
  color: var(--am-muted);
}

@media (max-width: 1250px) {
  .knowledge-layout {
    grid-template-columns: 180px minmax(0, 1fr);
  }

  .knowledge-side {
    display: none;
  }
}

@media (max-width: 850px) {
  .knowledge-layout {
    grid-template-columns: 1fr;
  }

  .knowledge-tree {
    display: none;
  }

  .filter-row {
    flex-direction: column;
  }

  .filter-row :deep(.el-select) {
    width: 100% !important;
  }
}
</style>
