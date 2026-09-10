# AgentMesh TypeScript SDK

V4 官方 Public API TypeScript 客户端，基于标准 `fetch`。

```ts
import { AgentMeshClient } from "@agentmesh/sdk";

const client = new AgentMeshClient({
  baseUrl: "https://agentmesh.example.com",
  apiKey: "<SERVICE_ACCOUNT_API_KEY>",
});

const run = await client.runTask(
  { task: "总结今天的项目风险" },
  { idempotencyKey: "run-2026-09-07-001" },
);
```

测试：

```powershell
cd sdk/typescript
npm ci
npm test
```
