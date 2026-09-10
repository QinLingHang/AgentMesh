# AgentMesh v1.0 — Resume Project Guide

This document is the resume-facing companion to the P12 release artifacts. It
describes the original v1.0 baseline. Capabilities introduced only in later
development branches should be described separately.

## Recommended project title

**AgentMesh — Multi-Agent Runtime and Enterprise Agent Platform**

中文可写：

**AgentMesh 多智能体运行时与企业级 Agent 平台**

## One-line project summary

> 基于 Go + Python + React 构建多智能体平台 AgentMesh，完成项目级 Agent
> 编排、RAG/Memory、Tool/MCP、安全审批、自适应路由、耐久任务运行时、多租户治理、
> BYOK、配额审计、生产部署门禁与真实浏览器 E2E 验证。

## Concise resume version

- 设计 **Go Control Plane + Python Agent Runtime + React UI** 多语言架构，
  支持项目级 Agent 执行、Knowledge/RAG、长期 Memory、Tool/MCP 与运行 Trace。
- 构建耐久任务执行链路，引入 **Queue、Worker Heartbeat、Lease/Fencing、
  Idempotency、Backpressure、Deadline/Cancel、Recovery、Circuit Breaker**，
  提升长任务和异常场景下的执行可靠性。
- 实现 **Organization/Workspace/Project 多租户治理、RBAC/IDOR 防护、BYOK、
  Quota/Usage、Audit/Redaction**，并通过 Go/Python/React 回归、真实 Chrome E2E、
  Release Validator 与隐私扫描完成发布候选验收。

## Detailed resume version

- 将产品拆分为 **Go 控制面、Python 智能体运行时、React/TypeScript 产品前端**：
  Go 负责认证、用户/项目、治理与耐久任务控制；Python 负责 Agent 编排、RAG、
  Memory、Tool/MCP 与路由智能；前端负责 Workspace 与独立 Run Details。
- 实现 Knowledge 与 Memory 的清晰边界：Project Knowledge 面向项目协作，
  GLOBAL Knowledge 与长期 Memory 保持用户私有，避免共享项目导致隐私越界。
- 在高风险 Tool/MCP 调用中实现 **Secure Action / Human-in-the-loop**：
  模型只能提出动作，真正副作用仍需经过权限、风险级别、审批和审计链路。
- 建立分布式可靠性机制，包括 **Durable Queue、Worker Registration/Heartbeat、
  Lease/Fencing、幂等执行、安全重试边界、Worker/Dispatcher Recovery、
  Graceful Shutdown**。
- 完成生产化与发布门禁：数据库迁移、`/livez`/`/readyz`、单公网 Gateway、
  same-origin API、TLS fail-closed、日志轮转、浏览器 E2E、Bundle Gate、
  Clean Staging、Secret/Privacy Scan 与严格归档校验。

## Architecture

```text
React / TypeScript
        ↓
Go Control Plane
        ↓
Python Agent Runtime
        ↓
MySQL / Redis / Milvus
```

### Go Control Plane

Responsibilities:

- authentication and session;
- user / project / organization boundaries;
- governance and RBAC;
- durable task lifecycle;
- quota / usage / audit;
- deployment and operational controls.

### Python Agent Runtime

Responsibilities:

- Agent orchestration;
- RAG and memory context;
- Tool / MCP execution;
- evaluation and routing;
- model interaction;
- runtime observability.

### React UI

Responsibilities:

- user-facing workspace;
- knowledge, capability and governance management;
- clean final answer;
- separate Run Details for DAG, Trace, latency, cost and evaluation evidence.

## Interview talking points

### Why Go + Python?

> Go provides a stable, strongly typed control plane for identity, task state,
> governance and operations, while Python keeps AI runtime logic close to the
> LLM/RAG/Agent ecosystem. The split also prevents model-runtime changes from
> destabilizing business-control code.

### Why lease + fencing?

> Lease gives temporary ownership, but fencing prevents an old worker that has
> lost ownership from committing stale results after another worker takes over.

### Why secure action instead of direct tool calls?

> LLM output is a proposal, not authorization. The platform separately applies
> permission, risk, approval and audit policy before allowing side effects.

### Why separate final answer and Trace?

> Product users need a clean answer. Engineers need execution evidence. Keeping
> them separate preserves usability without sacrificing observability.

## Testing strategy

The project uses layered validation:

```text
targeted unit / contract tests
→ Go / Python / React full regression
→ TypeScript + production build
→ real-browser E2E
→ release / source / privacy validation
→ final human acceptance
```

A concise engineering explanation:

> 自动化验收负责保护契约和回归，最终人工验收负责确认真实产品可用性和交互体验，
> 两者分开可以避免“测试通过但产品不好用”，也避免人工测试替代可重复验证。

## Suggested technology keywords

`Go`, `Python`, `FastAPI`, `React`, `TypeScript`, `MySQL`, `Redis`, `Milvus`,
`Agent`, `RAG`, `Memory`, `MCP`, `Tool Calling`, `SSE`, `JWT`, `RBAC`, `BYOK`,
`Durable Queue`, `Lease/Fencing`, `Idempotency`, `Observability`, `Docker`,
`Browser E2E`.

Only keep keywords that you can explain from the code.

## Scope boundaries

For the original v1.0 release, do not claim as completed:

- Kubernetes / Helm / Terraform delivery;
- enterprise SSO / SCIM;
- external billing-provider integration;
- arbitrary local desktop control;
- mobile client;
- cloud-vendor-specific deployment automation.

Later V2/V3/V4 development work should be introduced as subsequent evolution,
not silently folded into the original release baseline.

## Recommended final resume entry

**AgentMesh 多智能体运行时与企业级 Agent 平台｜Go / Python / React**

- 设计 Go Control Plane + Python Agent Runtime 多语言架构，完成项目级 Agent
  执行、Knowledge/RAG、长期 Memory、Tool/MCP、SSE Trace 与运行可观测性。
- 构建 Durable Queue、Worker Heartbeat、Lease/Fencing、幂等、Backpressure、
  Deadline/Cancel 与故障恢复机制，覆盖长任务和分布式异常边界。
- 实现 Organization/Workspace/Project 多租户治理、RBAC/IDOR、BYOK、
  Quota/Usage、Audit/Redaction，并通过真实浏览器 E2E、生产构建和发布隐私门禁。

Keep the final wording aligned with the exact branch and acceptance report used
during the interview.
