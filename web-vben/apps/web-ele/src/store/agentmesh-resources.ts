import type {
  Agent,
  Conversation,
  MCPServer,
  PluginInfo,
  Project,
  Task,
  Tool,
} from '#/api/agentmesh';

import { computed, ref } from 'vue';

import { defineStore } from 'pinia';

import {
  listAgents,
  listConversations,
  listMCPServers,
  listPlugins,
  listProjects,
  listTasks,
  listTools,
} from '#/api/agentmesh';

export const useAgentMeshResourcesStore = defineStore(
  'agentmesh-resources',
  () => {
    const agents = ref<Agent[]>([]);
    const conversations = ref<Conversation[]>([]);
    const projects = ref<Project[]>([]);
    const tasks = ref<Task[]>([]);
    const tools = ref<Tool[]>([]);
    const mcpServers = ref<MCPServer[]>([]);
    const plugins = ref<PluginInfo[]>([]);
    const loading = ref(false);
    const lastError = ref('');

    const activeAgents = computed(() =>
      agents.value.filter(
        (item) => String(item.status).toUpperCase() === 'ACTIVE',
      ),
    );
    const enabledTools = computed(() =>
      tools.value.filter((item) => item.enabled),
    );
    const enabledMcp = computed(() =>
      mcpServers.value.filter((item) => item.enabled),
    );

    async function refreshAll() {
      loading.value = true;
      lastError.value = '';
      const results = await Promise.allSettled([
        listAgents(),
        listConversations(),
        listProjects(),
        listTasks(),
        listTools(),
        listMCPServers(),
        listPlugins(),
      ]);
      const assign = <T>(index: number, target: { value: T[] }) => {
        const result = results[index];
        if (result?.status === 'fulfilled') target.value = result.value as T[];
      };
      assign<Agent>(0, agents);
      assign<Conversation>(1, conversations);
      assign<Project>(2, projects);
      assign<Task>(3, tasks);
      assign<Tool>(4, tools);
      assign<MCPServer>(5, mcpServers);
      assign<PluginInfo>(6, plugins);
      const rejected = results.find((item) => item.status === 'rejected');
      if (rejected?.status === 'rejected')
        lastError.value =
          rejected.reason instanceof Error
            ? rejected.reason.message
            : String(rejected.reason);
      loading.value = false;
    }

    async function refreshConversations() {
      conversations.value = await listConversations();
    }
    async function refreshProjects() {
      projects.value = await listProjects();
    }
    async function refreshTasks() {
      tasks.value = await listTasks();
    }
    async function refreshAgents() {
      agents.value = await listAgents();
    }
    async function refreshTools() {
      tools.value = await listTools();
    }
    async function refreshMcp() {
      mcpServers.value = await listMCPServers();
    }
    async function refreshPlugins() {
      plugins.value = await listPlugins();
    }

    return {
      agents,
      activeAgents,
      conversations,
      projects,
      tasks,
      tools,
      enabledTools,
      mcpServers,
      enabledMcp,
      plugins,
      loading,
      lastError,
      refreshAll,
      refreshConversations,
      refreshProjects,
      refreshTasks,
      refreshAgents,
      refreshTools,
      refreshMcp,
      refreshPlugins,
    };
  },
);
