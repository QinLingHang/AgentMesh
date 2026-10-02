<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';

import MetricCard from '#/components/agentmesh/MetricCard.vue';
import PageHeader from '#/components/agentmesh/PageHeader.vue';
import { useAgentMeshAuthStore } from '#/store/agentmesh-auth';
import { useAgentMeshResourcesStore } from '#/store/agentmesh-resources';

const router = useRouter();
const auth = useAgentMeshAuthStore();
const resources = useAgentMeshResourcesStore();
const initials = computed(() =>
  (auth.user?.displayName || auth.user?.email || 'AM')
    .slice(0, 2)
    .toUpperCase(),
);
const completed = computed(
  () =>
    resources.tasks.filter(
      (item) => String(item.status).toUpperCase() === 'COMPLETED',
    ).length,
);
onMounted(() => resources.refreshAll());
</script>

<template>
  <div class="am-page profile-page">
    <PageHeader
      eyebrow="PROFILE"
      title="个人主页"
      description="查看账户信息、工作概况，并快速进入常用设置。"
    />
    <section class="profile-hero am-card">
      <div class="profile-avatar">{{ initials }}</div>
      <div>
        <h2>{{ auth.user?.displayName || 'AgentMesh 用户' }}</h2>
        <p>{{ auth.user?.email }}</p>
        <el-tag type="success" round>
          {{ auth.user?.status || 'ACTIVE' }}
        </el-tag>
      </div>
      <div class="hero-actions">
        <el-button @click="router.push('/agentmesh/model-settings')">
          模型设置
</el-button><el-button type="primary" @click="router.push('/agentmesh/workspace')">
          返回工作台
        </el-button>
      </div>
    </section>
    <div class="am-metrics" style="margin-top: 16px">
      <MetricCard label="项目" :value="resources.projects.length" /><MetricCard
        label="会话"
        :value="resources.conversations.length"
      /><MetricCard
        label="智能体"
        :value="resources.agents.length"
      /><MetricCard label="已完成任务" :value="completed" tone="success" />
    </div>
    <div class="profile-grid">
      <section class="am-card quick-card">
        <h3>常用入口</h3>
        <button @click="router.push('/agentmesh/workspace')">
          <span>⌂</span>
          <div><b>工作台</b><small>继续最近会话或新建任务</small></div>
          <em>→</em>
</button><button @click="router.push('/agentmesh/model-settings')">
          <span>▤</span>
          <div><b>模型设置</b><small>管理个人 BYOK 模型服务</small></div>
          <em>→</em>
</button><button @click="router.push('/agentmesh/governance')">
          <span>⬡</span>
          <div><b>治理与安全</b><small>项目权限、成本和审计</small></div>
          <em>→</em>
        </button>
      </section>
      <section class="am-card quick-card">
        <h3>最近会话</h3>
        <button
          v-for="conversation in resources.conversations.slice(0, 5)"
          :key="conversation.id"
          @click="router.push('/agentmesh/workspace')"
        >
          <span>◌</span>
          <div>
            <b>{{ conversation.title }}</b><small>{{
              conversation.lastMessageAt
                ? new Date(conversation.lastMessageAt).toLocaleString()
                : '暂无消息'
            }}</small>
          </div>
          <em>→</em>
        </button>
        <div v-if="resources.conversations.length === 0" class="mini-empty">
          还没有会话
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.profile-hero {
  display: flex;
  gap: 16px;
  align-items: center;
  padding: 22px;
}

.profile-avatar {
  display: grid;
  place-items: center;
  width: 72px;
  height: 72px;
  font-size: 22px;
  font-weight: 850;
  color: var(--am-primary);
  background: linear-gradient(135deg, #dcd4ff, #f5f1ff);
  border-radius: 22px;
}

.profile-hero h2 {
  margin: 0 0 4px;
}

.profile-hero p {
  margin: 0 0 7px;
  font-size: 11px;
  color: var(--am-muted);
}

.hero-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.profile-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 16px;
}

.quick-card {
  padding: 16px;
}

.quick-card h3 {
  margin: 0 0 10px;
}

.quick-card button {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  width: 100%;
  padding: 10px 0;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--am-border);
}

.quick-card button > span {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  color: var(--am-primary);
  background: var(--am-primary-soft);
  border-radius: 9px;
}

.quick-card b,
.quick-card small {
  display: block;
}

.quick-card b {
  font-size: 10px;
}

.quick-card small {
  margin-top: 2px;
  font-size: 8px;
  color: var(--am-muted);
}

.quick-card em {
  font-style: normal;
  color: var(--am-muted);
}

.mini-empty {
  padding: 20px;
  font-size: 10px;
  color: var(--am-muted);
  text-align: center;
}

@media (max-width: 800px) {
  .profile-grid {
    grid-template-columns: 1fr;
  }

  .profile-hero {
    flex-wrap: wrap;
    align-items: flex-start;
  }

  .hero-actions {
    width: 100%;
    margin-left: 0;
  }
}
</style>
