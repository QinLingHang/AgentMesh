import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    path: '/agentmesh/login',
    name: 'AgentMeshLogin',
    component: () => import('#/views/agentmesh/auth/index.vue'),
    meta: {
      title: 'AgentMesh 登录',
      ignoreAccess: true,
      hideInMenu: true,
      hideInTab: true,
    },
  },
  {
    path: '/agentmesh',
    component: () => import('#/layouts/AgentMeshLayout.vue'),
    redirect: '/agentmesh/workspace',
    meta: {
      title: 'AgentMesh',
      ignoreAccess: true,
      hideInMenu: true,
      hideInTab: true,
    },
    children: [
      {
        path: 'workspace',
        name: 'AgentMeshWorkspace',
        component: () => import('#/views/agentmesh/workspace/index.vue'),
        meta: { title: '工作台' },
      },
      {
        path: 'agents',
        name: 'AgentMeshAgents',
        component: () => import('#/views/agentmesh/agents/index.vue'),
        meta: { title: '智能体' },
      },
      {
        path: 'knowledge',
        name: 'AgentMeshKnowledge',
        component: () => import('#/views/agentmesh/knowledge/index.vue'),
        meta: { title: '知识库 RAG' },
      },
      {
        path: 'memory',
        name: 'AgentMeshMemory',
        component: () => import('#/views/agentmesh/memory/index.vue'),
        meta: { title: '长期记忆' },
      },
      {
        path: 'capabilities',
        name: 'AgentMeshCapabilities',
        component: () => import('#/views/agentmesh/capabilities/index.vue'),
        meta: { title: '工具 / MCP' },
      },
      {
        path: 'tasks',
        name: 'AgentMeshTasks',
        component: () => import('#/views/agentmesh/tasks/index.vue'),
        meta: { title: '任务记录' },
      },
      {
        path: 'model-settings',
        name: 'AgentMeshModelSettings',
        component: () => import('#/views/agentmesh/model-settings/index.vue'),
        meta: { title: '模型设置' },
      },
      {
        path: 'governance',
        name: 'AgentMeshGovernance',
        component: () => import('#/views/agentmesh/governance/index.vue'),
        meta: { title: '治理与安全' },
      },
      {
        path: 'ecosystem',
        name: 'AgentMeshEcosystem',
        component: () => import('#/views/agentmesh/ecosystem/index.vue'),
        meta: { title: '生态中心' },
      },
      {
        path: 'profile',
        name: 'AgentMeshProfile',
        component: () => import('#/views/agentmesh/profile/index.vue'),
        meta: { title: '个人主页' },
      },
    ],
  },
];

export default routes;
