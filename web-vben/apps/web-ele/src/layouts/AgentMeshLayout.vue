<script setup lang="ts">
import { computed, onBeforeMount, onBeforeUnmount, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useAgentMeshAuthStore } from '#/store/agentmesh-auth';
import { useAgentMeshResourcesStore } from '#/store/agentmesh-resources';

import '../styles/agentmesh-element-light.css';

const router = useRouter();
const route = useRoute();
const auth = useAgentMeshAuthStore();
const resources = useAgentMeshResourcesStore();

const navigation = [
  { path: '/agentmesh/workspace', label: '工作台', icon: '⌂' },
  { path: '/agentmesh/agents', label: '智能体', icon: '◉' },
  { path: '/agentmesh/knowledge', label: '知识库 RAG', icon: '▣' },
  { path: '/agentmesh/memory', label: '长期记忆', icon: '◎' },
  { path: '/agentmesh/capabilities', label: '工具 / MCP', icon: '◇' },
  { path: '/agentmesh/tasks', label: '任务记录', icon: '☷' },
  { path: '/agentmesh/model-settings', label: '模型设置', icon: '▤' },
  { path: '/agentmesh/governance', label: '治理与安全', icon: '⬡' },
  { path: '/agentmesh/ecosystem', label: '生态中心', icon: '✦' },
];

const currentTitle = computed(
  () =>
    navigation.find((item) => route.path.startsWith(item.path))?.label ??
    'AgentMesh',
);
const initials = computed(() =>
  (auth.user?.displayName || auth.user?.email || 'AM')
    .slice(0, 2)
    .toUpperCase(),
);

onBeforeMount(() => {
  document.documentElement.classList.add('agentmesh-ui-light');
});

onBeforeUnmount(() => {
  document.documentElement.classList.remove('agentmesh-ui-light');
});

async function signOut() {
  await auth.signOut();
  await router.replace('/agentmesh/login');
}

onMounted(async () => {
  const user = auth.user ?? (await auth.restoreSession());
  if (!user) {
    await router.replace({
      path: '/agentmesh/login',
      query: { redirect: route.fullPath },
    });
    return;
  }
  await resources.refreshAll();
});
</script>

<template>
  <div class="agentmesh-app am-shell">
    <aside class="am-shell-sidebar">
      <router-link class="am-brand" to="/agentmesh/workspace">
        <div class="am-brand-mark">◇</div>
        <div class="am-brand-copy">
          <div class="am-brand-title">AgentMesh</div>
          <div class="am-brand-subtitle">AI Native Agent Platform</div>
        </div>
      </router-link>

      <nav class="am-nav" aria-label="AgentMesh 导航">
        <router-link
          v-for="item in navigation"
          :key="item.path"
          :to="item.path"
          class="am-nav-link"
        >
          <span class="am-nav-icon">{{ item.icon }}</span>
          <span class="am-nav-copy">{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="am-sidebar-footer">
        <router-link
          to="/agentmesh/profile"
          class="am-user-card"
          style="color: inherit; text-decoration: none"
        >
          <div class="am-user-avatar">{{ initials }}</div>
          <div class="am-user-copy" style="flex: 1; min-width: 0">
            <div
              style="
                overflow: hidden;
                text-overflow: ellipsis;
                font-size: 12px;
                font-weight: 800;
                white-space: nowrap;
              "
            >
              {{ auth.user?.displayName || 'AgentMesh 用户' }}
            </div>
            <div
              style="
                overflow: hidden;
                text-overflow: ellipsis;
                font-size: 10px;
                color: var(--am-muted);
                white-space: nowrap;
              "
            >
              {{ auth.user?.email }}
            </div>
          </div>
          <button
            type="button"
            class="am-count-pill"
            style="padding: 0 8px"
            title="退出"
            @click.prevent="signOut"
          >
            ↪
          </button>
        </router-link>
      </div>
    </aside>

    <main class="am-shell-main">
      <header class="am-shell-topbar">
        <div class="am-topbar-title">{{ currentTitle }}</div>
        <div class="am-topbar-spacer"></div>
        <span class="am-count-pill">◉ {{ resources.activeAgents.length }} 个智能体</span>
        <span class="am-count-pill">◇
          {{
            resources.tools.length +
            resources.mcpServers.length +
            resources.plugins.length
          }}
          项能力</span>
        <span
          v-if="resources.lastError"
          class="am-count-pill"
          style="color: var(--am-danger)"
          >部分服务不可用</span>
      </header>
      <section class="am-shell-content">
        <router-view />
      </section>
    </main>
  </div>
</template>
