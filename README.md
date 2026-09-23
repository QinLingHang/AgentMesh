# AgentMesh

**Intent-Aware Agent Platform · Adaptive Multi-Agent Orchestration · Distributed Agent Runtime · AI Application Infrastructure**

面向多用户、多项目场景的 Agent 应用与运行时平台。

基于 **Go Control Plane + Python Agent Runtime + React / TypeScript** 构建，提供从自然语言意图理解、执行路径决策、语义任务规划、多 Agent 编排、知识检索、长期记忆、Tool / MCP 调用，到分布式执行、运行时恢复、可靠结果交付和多租户治理的完整工程实践。

[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](LICENSE)
![Go](https://img.shields.io/badge/Go-Control%20Plane-00ADD8)
![Python](https://img.shields.io/badge/Python-Agent%20Runtime-3776AB)
![React](https://img.shields.io/badge/React-TypeScript-149ECA)
![Kafka](https://img.shields.io/badge/Kafka-Event%20Plane-231F20)

---

# 📖 项目介绍

AgentMesh 是一个面向真实任务执行的 Agent 应用与运行时平台。

与简单的 LLM API 封装、固定 Workflow 或单 Agent Tool Loop 不同，AgentMesh 重点解决：

> **如何先理解用户真正想做什么，再决定应该直接调用模型回答，还是进入完整 Agent Runtime；进入 Runtime 后，如何动态发现并组合 Agent、Tool、MCP、Knowledge、Memory 等能力，并在权限、审批、Worker 故障、结果交付异常和长会话场景下保持执行过程可观测、可恢复和可治理。**

平台采用多语言分层架构：

| 模块            | 技术                           | 核心职责                                                                 |
| :------------ | :--------------------------- | :------------------------------------------------------------------- |
| Control Plane | Go / Gin                     | API、认证、Intent Routing、Durable Task、资源管理与治理                           |
| Agent Runtime | Python / FastAPI / LangGraph | Semantic Understanding、Planner、Multi-Agent、DAG、RAG、Memory、Tool / MCP |
| Web           | React / TypeScript           | Workspace、Run Details、Knowledge、Approval 与 Governance                |
| Storage       | MySQL / Redis / Milvus       | 业务持久化、运行时记忆与向量检索                                                     |
| Event Plane   | Kafka / SQLite Outbox        | 执行结果可靠交付与异步事件传输                                                      |

**项目核心目标：构建能够理解用户意图，并具备可规划、可协作、可观测、可恢复、可治理和可扩展能力的 Agent Runtime。**

---

# ✨ 核心功能

| 能力模块                 | 功能                                                           |
| :------------------- | :----------------------------------------------------------- |
| Intent-Aware Routing | 自然语言意图理解、FAST_PATH / RUNTIME 二元执行决策                          |
| Capability Discovery | Agent、Tool、MCP、Knowledge 等运行时能力发现                            |
| Adaptive Workflow    | Semantic Planner、ExecutionPlan、Plan Validation、Plan Compiler |
| Multi-Agent          | 动态发现、智能路由、Hybrid DAG、Fan-out / Fan-in、多 Agent 协作             |
| Agent Runtime        | Internal / LangGraph / HTTP / A2A Agent 统一执行                 |
| Runtime Recovery     | Quality Gate、Repair、Reschedule、Replan                        |
| Multimodal RAG       | 文本与视觉知识检索、混合检索、授权与引用                                         |
| Memory               | 长期记忆、上下文压缩、会话持久化与恢复                                          |
| Tool / MCP           | 工具发现、参数校验、执行反馈、审批与治理                                         |
| Distributed Runtime  | Durable Queue、多 Worker、Lease、Fencing                         |
| Reliability          | 幂等执行、故障恢复、Kafka 可靠结果交付                                       |
| Multi-Tenant         | Organization、Workspace、RBAC、资源隔离                             |
| Model Gateway        | 多模型配置、BYOK、模型路由与密钥隔离                                         |
| Platform Ecosystem   | Public API、SDK、Agent Template、Marketplace                    |
| Observability        | Routing、Planner、DAG、Tool、RAG、调度、质量门控与故障诊断                    |

---

# 🏗 系统架构

AgentMesh 将执行入口、控制面、Agent Runtime、执行层和基础设施可靠性进行分层。

```text
                         User Query
                             │
                             ▼
                 ┌──────────────────────┐
                 │ React / TypeScript   │
                 │      Workspace       │
                 └──────────┬───────────┘
                            │
                         HTTP / SSE
                            │
                            ▼
             ┌──────────────────────────────┐
             │       Go Control Plane       │
             │                              │
             │ Auth / Project / Governance  │
             │ Intent Execution Decision    │
             │ Durable Task / API           │
             └──────────────┬───────────────┘
                            │
                 ┌──────────┴───────────┐
                 │                      │
                 ▼                      ▼
             FAST_PATH               RUNTIME
                 │                      │
                 ▼                      ▼
            Model Provider     Python Agent Runtime
                                      │
                                      ▼
                           Semantic Understanding
                                      │
                                      ▼
                           Capability Discovery
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                    ▼                 ▼                 ▼
                 Planner           Tool / MCP       RAG / Memory
                    │
                    ▼
             ExecutionPlan
                    │
                    ▼
              Plan Validation
                    │
                    ▼
            Adaptive Scheduler
                    │
                    ▼
               Hybrid DAG
                    │
          ┌─────────┼──────────┐
          ▼         ▼          ▼
      Internal   LangGraph   HTTP / A2A
       Agent      Agent        Agent
          │         │          │
          └─────────┼──────────┘
                    │
                    ▼
               Quality Gate
                    │
           Repair / Reschedule
                    │
                    ▼
               Final Result
                    │
                    ▼
              SQLite Outbox
                    │
                    ▼
                  Kafka
                    │
                    ▼
             Go Consumer
                    │
                    ▼
                  MySQL
```

---

## 架构职责

### Go Control Plane

负责：

* API 与认证
* Organization / Workspace / Project
* 用户请求入口
* Intent Execution Decision
* FAST_PATH / RUNTIME 路径选择
* Durable Task
* RBAC / Governance
* Tool Approval
* Resource Ownership
* Worker 与任务状态管理
* MySQL 持久化

Go 控制面只负责决定顶层执行路径：

```text
FAST_PATH
RUNTIME
```

它不会重新实现 Python Runtime 内部的 Planner、Tool Loop、RAG 或 MCP 执行逻辑。

---

### Python Agent Runtime

负责进入 `RUNTIME` 后的智能执行。

主要包括：

```text
Semantic Understanding
Capability Discovery
Semantic Planner
ExecutionPlan
Plan Validation
Adaptive Scheduler
Hybrid DAG
Agent Routing
Tool / MCP
RAG
Memory
Quality Gate
Repair
Reschedule
Replan
```

Runtime 根据用户当前请求、会话上下文、附件、授权范围和可用能力，动态判断实际需要使用哪些能力。

---

### React Web

提供用户侧 Workspace 和治理界面，包括：

```text
Conversation
Run Details
Knowledge
Memory
Routing Trace
Tool Approval
Runtime Status
Governance
```

普通用户只需要描述自己的目标。

用户不需要知道：

```text
RAG
Vector Search
Capability Discovery
MCP Routing
Runtime Internal Mode
```

这些属于平台内部执行能力。

---

### 基础设施

```text
MySQL
    业务数据
    Conversation
    Durable Task
    Runtime State

Redis
    Cache
    Runtime Working Memory

Milvus
    Project Knowledge
    Vector Retrieval

Kafka
    Runtime Result Event Delivery

SQLite Outbox
    Runtime 本地 Durable Result Buffer
```

Go Durable Runtime 负责任务可靠调度。

Python Agent Runtime 负责任务内部智能执行。

Kafka 负责执行结果可靠交付。

三者职责相互独立。

---

# 🧭 1. Intent-Aware Execution Routing

P23 引入了新的用户请求入口决策机制。

过去仅依靠规则或任务复杂度判断执行路径，会出现：

```text
用户真实意图 ≠ 表面关键词
```

从而造成：

```text
应该直接回答的请求进入 Runtime

或者

真正需要 Tool / Knowledge / Agent 的请求被错误地直接交给模型
```

因此 AgentMesh 将入口决策调整为：

```text
User Query
    │
    ▼
Conversation Context
    │
    ▼
Attachment Context
    │
    ▼
Intent Understanding
    │
    ▼
Execution Decision
    │
    ├─────────────── FAST_PATH
    │
    └─────────────── RUNTIME
```

---

## FAST_PATH

适用于不需要 Runtime 能力的请求。

典型链路：

```text
User Query
    │
    ▼
Go Control Plane
    │
    ▼
FAST_PATH
    │
    ▼
Model Provider
    │
    ▼
Streaming Answer
```

FAST_PATH 不进入完整 Agent Runtime，因此具有更低的执行开销。

例如：

```text
普通问答
文本解释
无需外部能力的生成任务
基于当前已提供内容可以直接完成的请求
```

---

## RUNTIME

当请求需要平台能力时进入 Runtime：

```text
User Query
    │
    ▼
RUNTIME
    │
    ▼
Semantic Understanding
    │
    ▼
Capability Discovery
    │
    ├── Agent
    ├── Tool
    ├── MCP
    ├── Knowledge
    ├── Memory
    └── Workflow
```

进入 Runtime 并不意味着一定执行 RAG 或 Tool。

真正需要使用什么能力，由 Runtime 根据当前任务继续判断。

---

## Intent Understanding

Intent Understanding 关注的不是简单关键词分类，而是理解：

```text
用户想完成什么目标？

当前请求是否依赖已有上下文？

是否存在附件？

是否需要项目资源？

是否需要读取或修改外部状态？

是否存在工具调用？

是否需要知识证据？

是否涉及审批或高风险副作用？
```

因此：

```text
Intent
    ≠
Keyword Matching
```

---

## Authoritative Decision

模型可以参与语义理解，但最终执行路径仍受到平台规则和治理边界约束。

决策过程不会允许模型通过自然语言绕过：

```text
RBAC
Project Scope
Tool Governance
Approval
Knowledge Authorization
MCP Scope
Resource Ownership
```

对于需要受治理能力的任务，必须进入 Runtime。

---

## Attachment-Aware Routing

上传文件并不意味着一定进入 Runtime。

例如：

```text
用户上传一份文档
然后要求：
“总结一下这份内容”
```

如果当前请求可以直接基于已提供附件内容回答，可以继续走：

```text
FAST_PATH
```

而不是仅因为存在附件就强制进入完整 Runtime。

---

## Continuation-Aware Routing

执行路径同时考虑会话上下文。

例如：

```text
第一轮：
“读取项目中的配置文件”

第二轮：
“把刚才那个改掉”
```

第二轮虽然文本很短，但它依赖上一轮建立的执行对象与上下文，因此不能只依据当前字符串判断。

---

# 🤖 2. Adaptive Multi-Agent Orchestration

进入 Runtime 后，如果任务需要复杂执行，AgentMesh 可以进一步进入 Adaptive Workflow。

完整链路：

```text
RUNTIME
    │
    ▼
Semantic Understanding
    │
    ▼
Capability Discovery
    │
    ▼
Semantic Planner
    │
    ▼
ExecutionPlan
    │
    ▼
Plan Validation
    │
    ▼
Adaptive Scheduler
    │
    ▼
Plan Compiler
    │
    ▼
Hybrid Dynamic DAG
    │
    ▼
DAGExecutor
    │
 ┌──┼────────────┐
 ▼  ▼            ▼
Internal     LangGraph
Agent        Agent
                 │
          HTTP / A2A
    │
    ▼
Quality Gate
    │
 ┌──┼────────────┐
PASS REPAIR     FAIL
 │     │          │
 │     │      Reschedule
 │     │          │
 │     └────── Replan
 │
 ▼
Synthesis
 │
 ▼
Final Answer
```

---

## Semantic Planner

Semantic Planner 回答：

> **这个复杂任务需要完成哪些步骤？**

它不会直接决定具体由哪个 Agent 执行。

例如：

```text
分析系统架构和安全风险，
并根据两部分分析结果给出最终优化方案。
```

可以形成：

```text
Architecture Analysis ─┐
                       ├── Solution Design
Security Analysis ─────┘
```

每个 Step 可以包含：

```text
step id
objective
required capability
dependencies
execution metadata
```

Planner：

```text
What to do
```

Scheduler：

```text
Who executes
```

---

## Plan Validation

Semantic Plan 在进入执行层前必须经过验证。

主要检查：

```text
Duplicate Step ID
Self Dependency
Missing Dependency
DAG Cycle
Step Limit
Capability Validation
Planner Output Schema
Replan Validation
```

非法 Plan 不会直接进入 Agent 执行。

Planner 超时、解析失败或返回非法结构时，根据任务类型执行：

```text
bounded fallback
或
fail closed
```

---

## Hybrid Dynamic DAG

AgentMesh 不局限于固定：

```text
single
parallel
sequential
```

ExecutionPlan 可以编译成混合依赖 DAG：

```text
         A ─────┐
                ├──── C ────┐
         B ─────┘            │
              └──── D ──────┤
                             ▼
                             E
```

支持：

```text
Serial Dependency
Parallel Ready Set
Fan-out
Fan-in
Hybrid Dependency
Conditional Execution
Optional Execution
Dependency-aware Scheduling
```

只有依赖满足的 Step 才会进入 Ready Set。

---

## Heterogeneous Agent Execution

同一个 ExecutionPlan 可以组合：

```text
Internal Agent
LangGraph Agent
HTTP Agent
A2A Agent
```

例如：

```text
Internal Agent ────┐
                   ├── HTTP Agent ─── A2A Agent
LangGraph Agent ───┘
```

因此 AgentMesh 的 Multi-Agent 不是简单把多个 Prompt 串起来，而是：

```text
Semantic Planning
+
Capability Routing
+
Heterogeneous Agent Execution
+
Dynamic DAG
```

---

# 🔍 3. Knowledge & Multimodal RAG

AgentMesh 支持文本与视觉知识检索。

与传统“用户主动选择知识库”的模式不同，Knowledge / RAG 属于 Runtime 内部能力。

用户只需要正常表达问题。

Runtime 根据：

```text
User Intent
Conversation Context
Project Scope
Available Knowledge
Authorization
Evidence Requirement
```

决定是否需要检索项目知识。

---

## Knowledge Flow

```text
Document / Image
       │
       ▼
Knowledge Ingest
       │
       ▼
Chunking / Embedding
       │
       ▼
     Milvus
       │
       ▼
Hybrid Retrieval
       │
       ▼
     Rerank
       │
       ▼
Citation / Evidence
       │
       ▼
Agent Context
```

---

## Retrieval Mode

内部支持：

```text
TEXT
VISUAL
HYBRID
```

Runtime 自动选择合适的知识能力。

终端用户不需要选择：

```text
RAG ON
RAG OFF
Knowledge Mode
```

---

## Evidence & Citation

当任务明确依赖项目知识时，Runtime 对检索结果执行证据治理。

包括：

```text
Project Scope Validation
Authorization
Evidence Provenance
Citation
Cross-user Isolation
Knowledge Boundary
```

未经授权的 Knowledge 不会被作为当前任务证据使用。

---

# 🧠 4. Conversation & Memory

AgentMesh 将：

```text
Conversation History
User Memory
Runtime Working Memory
Project Knowledge
```

进行分层管理。

| 组件             | 职责                       |
| :------------- | :----------------------- |
| MySQL          | 完整会话历史与业务持久化             |
| Redis          | Runtime Working Memory   |
| User Memory    | User-global 长期记忆         |
| Memory Capsule | 长上下文压缩与记忆延续              |
| Milvus         | Project-scoped Knowledge |

核心边界：

```text
Memory
→ User-global

Knowledge
→ Project-scoped
```

避免不同项目之间发生非预期知识串用。

---

## Conversation History Reliability

长会话支持：

```text
Historical Message Pagination
Conversation Persistence
Context Compaction
Memory Capsule
Redis-loss Recovery
Refresh Recovery
Long Conversation Continuity
```

历史消息加载时保持可见锚点稳定，避免追加旧历史导致页面跳动。

---

# 🔧 5. Tool & MCP

AgentMesh 支持：

```text
Internal Tool
HTTP Tool
MCP Tool
Desktop Tool
```

---

## Tool Execution

```text
Available Tool Schema
        │
        ▼
       LLM
        │
        ▼
     ToolCall
 name + arguments
        │
        ▼
Tool Governance
        │
        ▼
Approval Check
        │
        ▼
Tool Registry / MCP
        │
        ▼
Real Execution
        │
        ▼
Tool Result
        │
        ▼
       LLM
        │
        ▼
Continue / Final
```

模型只负责产生结构化 ToolCall。

真正执行发生在 Runtime / Tool Registry / MCP Adapter 中。

---

## Tool Governance

工具执行受到：

```text
Project Scope
Resource Ownership
Risk Level
Authorization
Human Approval
Runtime State
```

约束。

例如高风险删除操作：

```text
local.fs.delete
```

需要经过：

```text
Tool Governance
    │
    ▼
AUTH_REQUIRED
    │
    ▼
Approval Card
```

在用户批准之前不会发生实际副作用。

---

## Approval Resume

Approval 不会重新创建整个任务。

原 Task 在获得：

```text
Approve
或
Reject
```

结果后继续处理。

Reject 后：

```text
no new Task
no side effect
no replay
```

---

# 🛡 6. Side-Effect Replay Protection

AgentMesh 对具有业务副作用的执行采取严格恢复策略。

包括：

```text
Tool Action
HTTP Agent Action
A2A Agent Action
Approval-gated Action
```

已完成的副作用不会因为普通质量评分不足而自动再次执行。

保护机制包括：

```text
Bounded Repair
Bounded Replan
Completed Step Carry-forward
Completed Side-effect Carry-forward
HTTP / A2A Replay Protection
Tool Replay Protection
Idempotency
Fencing
```

---

# ⚙️ 7. Distributed Agent Runtime

AgentMesh 支持多 Worker 分布式执行。

| 机制                   | 作用              |
| :------------------- | :-------------- |
| Durable Queue        | 持久化任务队列         |
| Worker Registration  | Worker 注册       |
| Heartbeat            | 存活检测            |
| Lease                | 执行所有权           |
| Fencing              | 防止旧 Worker 提交结果 |
| Idempotent Execution | 防止重复业务执行        |
| Backpressure         | 负载控制            |
| Deadline / Cancel    | 执行期限与取消         |
| Worker Recovery      | Worker 故障恢复     |
| Dispatcher HA        | 调度器高可用          |

---

## Lease & Fencing

```text
Task
 │
 ▼
Durable Queue
 │
 ▼
Worker Assignment
 │
 ▼
Acquire Lease
 │
 ▼
Execute Agent
 │
 ▼
Validate Fencing
 │
 ▼
Commit Result
```

Worker 失联或 Lease 过期后，任务可以安全重新分配。

旧 Worker 恢复后，也不能利用过期 Fencing Token 覆盖当前执行结果。

---

# 📨 8. Reliable Result Delivery

Python Runtime 执行完成后使用 Durable Outbox + Kafka 交付结果。

```text
Python Agent Runtime
        │
        ▼
SQLite Durable Outbox
        │
        ▼
      Kafka
        │
        ▼
Go Runtime Consumer
        │
        ▼
Idempotency / Fencing
        │
        ▼
MySQL Transaction
        │
        ▼
Task COMPLETED
```

关键机制：

```text
Durable Outbox
At-Least-Once Delivery
RESULT_PENDING
Broker ACK
Business ACK
Fencing Validation
Consumer Recovery
DLQ
HTTP Compatibility
```

Go Durable Queue 负责任务调度。

Kafka 负责 Runtime 执行结果交付。

两者不是替代关系。

---

# 🔐 9. Multi-Tenant Governance

资源层级：

```text
User
 │
 ▼
Organization
 │
 ▼
Workspace / Project
 │
 ├── Agent
 ├── Knowledge
 ├── Conversation
 ├── Memory
 ├── Model
 ├── Tool
 └── MCP
```

核心治理能力：

```text
Organization
Workspace
RBAC
Project Scope
Resource Ownership
BYOK Secret Isolation
Knowledge Isolation
Conversation Isolation
Memory Isolation
Quota
Usage
Audit
```

Intent Router、Planner、Tool Loop、RAG 和 MCP 都不能绕过现有治理边界。

---

# 🔑 10. Model Gateway & BYOK

AgentMesh 使用统一 Model Provider 抽象。

支持：

```text
User Model Configuration
Project Model Configuration
Model Provider
BYOK
Provider Candidate
Model Routing
Secret Isolation
Usage Control
Governance Check
```

Runtime 不绑定单一模型厂商。

开发环境可以接入 OpenAI-compatible Provider。

生产环境可以由用户或项目配置自己的模型凭据。

---

# 🖥️ 11. Desktop Bridge

Desktop Bridge 用于扩展 Agent 对本地桌面环境的受控访问。

支持：

```text
Desktop Capability Discovery
Read-only Desktop Access
File Tool
Runtime Tool Integration
Governance Check
Runtime Trace
```

本地修改类操作仍受到：

```text
Risk Level
Authorization
Approval
Project Scope
```

约束。

---

# 🌐 12. Platform Ecosystem

AgentMesh 同时提供平台化能力：

```text
Public API
API Key
Service Account
Python SDK
TypeScript SDK
Agent Template
Agent Versioning
Plugin Registry
MCP Registry
Marketplace
```

通过 Registry、SDK 和 API 支持能力复用与第三方系统接入。

---

# 📊 13. Execution Trace & Observability

AgentMesh 提供完整运行追踪。

包括：

```text
Intent Understanding
Execution Decision
FAST_PATH / RUNTIME
Task Profile
Semantic Planning
Plan Validation
Capability Discovery
DAG Compilation
Scheduling Decision
Agent Assignment
Agent Execution
Knowledge Retrieval
Citation
Tool / MCP Invocation
Approval
Quality Evaluation
Repair
Reschedule
Replan
Runtime Error
Worker / Failover
Kafka / Outbox
Final Synthesis
```

可以回答：

```text
为什么这次请求进入 FAST_PATH？

为什么进入 Runtime？

Runtime 为什么需要 Knowledge？

为什么选择这个 Agent？

为什么调用这个 Tool？

为什么需要 Approval？

为什么发生 Repair？

为什么重新选择 Agent？

为什么重新规划？

哪个 Worker 执行了任务？

任务失败后如何恢复？
```

最终回答与详细 Trace 分离展示。

普通用户看到正常 Workspace。

需要分析问题时再进入 Run Details。

---

# 🛠 技术栈

| 层级              | 技术                               |
| :-------------- | :------------------------------- |
| Frontend        | React、TypeScript、Vite            |
| Control Plane   | Go、Gin                           |
| Agent Runtime   | Python、FastAPI、LangGraph、asyncio |
| Database        | MySQL                            |
| Cache / Memory  | Redis                            |
| Vector Database | Milvus                           |
| Event Plane     | Apache Kafka、SQLite Outbox       |
| Infrastructure  | Docker、Docker Compose、Nginx      |
| Security        | JWT、RBAC、BYOK                    |
| Communication   | HTTP、SSE、Kafka、A2A               |

---

# 📁 项目结构

```text
AgentMesh/
│
├── backend-go/
│   ├── cmd/
│   └── internal/
│       ├── handler/
│       ├── repository/
│       ├── runtime/
│       └── service/
│
├── runtime-python/
│   ├── app/
│   │   ├── semantics/
│   │   ├── planning/
│   │   ├── services/
│   │   ├── agents/
│   │   ├── rag/
│   │   └── eval/
│   └── tests/
│
├── web-react/
│   ├── src/
│   ├── tests/
│   └── e2e/
│
├── desktop-bridge/
├── sdk/
├── infra/
├── scripts/
│
├── docs/
│   ├── runtime/
│   ├── platform/
│   ├── operations/
│   ├── governance/
│   ├── memory/
│   ├── multimodal/
│   ├── security/
│   └── desktop/
│
├── docker-compose.yml
├── VERSION
├── LICENSE
└── README.md
```

---

# 🚀 快速开始

## 1. 环境要求

建议准备：

```text
Go
Python
Node.js
Docker Desktop
Docker Compose
```

---

## 2. 克隆项目

```bash
git clone https://github.com/QinLingHang/AgentMesh.git
cd AgentMesh
```

---

## 3. 启动基础设施

当前 Windows 本地开发模式：

```text
Windows
├── Go Control Plane
├── Python Agent Runtime
└── React / TypeScript

Docker Compose
└── agentmesh_runtime_mvp_full_v02
    ├── MySQL
    ├── Redis
    ├── Kafka
    ├── Milvus
    ├── etcd
    └── MinIO
```

检查：

```powershell
docker compose -p agentmesh_runtime_mvp_full_v02 ps
```

不要在已有开发数据的环境中随意执行：

```powershell
docker compose down -v
```

否则可能删除持久化数据。

---

## 4. 配置服务

参考：

```text
backend-go/.env.example
runtime-python/.env.example
```

配置：

```text
MySQL
Redis
Runtime
Model Provider
Kafka
Milvus
BYOK
```

---

## 5. Intent Routing 配置

P23 Intent-Aware Routing 使用：

```text
P23_DECISION_MODE
```

当前安全默认：

```text
P23_DECISION_MODE=OFF
```

可根据发布策略受控切换到新的 Intent Decision 路径。

`OFF` 用于保持兼容与回滚能力。

新的 Decision Mode 在启用后仍不会绕过：

```text
RBAC
Project Scope
Tool Governance
Knowledge Authorization
MCP Scope
Approval
```

---

## 6. Kafka Result Delivery

使用 Kafka Runtime Result Transport 时需要启用：

```text
Go Runtime Consumer
Python Kafka Result Transport
```

Kafka 只负责结果事件交付。

任务调度仍然由 Go Durable Runtime 负责。

---

## 7. 启动应用

分别启动：

```text
Go Control Plane
Python Agent Runtime
React Web
```

首次运行前需要完成数据库初始化和 Model Provider 配置。

---

# ✅ 测试

仓库包含：

```text
Go Unit / Integration Test
Python Runtime Test
React Contract Test
Browser E2E
Intent Routing Evaluation
Frozen Human Evaluation Set
Fault Injection
Performance Benchmark
```

---

## Go Control Plane

```powershell
cd backend-go
go test ./...
```

---

## Python Runtime

```powershell
cd runtime-python
python -m pytest -q
```

---

## React

```powershell
cd web-react
npm install
npm test
npm run build
```

---

## Browser E2E

需要本地：

```text
Go
Python
React
MySQL
Redis
Kafka
Milvus
```

运行：

```powershell
cd web-react
npm run test:e2e:v4-1
```

---

## P23 Intent Routing Evaluation

P23 提供固定评测资产和可复现评测工具。

包括：

```text
Binary Route Contract
Frozen Evaluation Fixture
Human-reviewed Evaluation Set
Authoritative Handling Validation
Real-stack Gate
HTTP Performance Benchmark
```

用于长期防止：

```text
Runtime Required Request
被错误送入 FAST_PATH

或

普通 Direct Request
被无意义送入 Runtime
```

---

## Reliability & Security

相关测试覆盖：

```text
Request Idempotency
SSE
Conversation History
Memory Isolation
Knowledge Isolation
RAG Authorization
Citation
Tool Governance
MCP Governance
Approval
Durable Queue
Worker Lease
Fencing
Kafka Outbox
Kafka Consumer
DLQ
Duplicate Event
Crash Recovery
Rollback
```

破坏性测试必须使用隔离 QA 资源。

不要停止共享基础设施，也不要清空开发数据库。

---

# 🧪 P23 Intent & Capability Routing

P23 的核心目标并不是增加一个新的执行引擎。

它解决的是：

> **在任务真正开始执行之前，先正确理解用户当前意图，并选择正确的顶层执行路径。**

最终架构保持：

```text
Go
│
├── FAST_PATH
│
└── RUNTIME
        │
        ├── Semantic Understanding
        ├── Capability Discovery
        ├── Planner
        ├── Agent
        ├── Tool
        ├── MCP
        ├── RAG
        ├── Memory
        └── Governance
```

P23 不创建：

```text
第二套 Agent Runtime
第二套 Tool Loop
第二套 RAG Pipeline
第二套 MCP Engine
```

而是继续复用已有 Runtime 能力。

这保证了新的 Intent Routing 不会破坏原有：

```text
P20 Conversation Reliability
P21 Distributed Runtime / Kafka
P22 RAG
V4 Governance
Tool Approval
Desktop Tool
```

能力边界。

---

# 📦 Release

已发布版本：

**AgentMesh v1.0.0**

[查看 GitHub Releases](https://github.com/QinLingHang/AgentMesh/releases)

Release Tag 表示对应历史稳定版本。

当前开发分支持续演进：

```text
Conversation Reliability
Distributed Runtime
Kafka Event Plane
Adaptive Semantic Workflow
RAG
Intent-Aware Routing
Capability Discovery
Governance
```

使用项目时请根据实际需求选择：

```text
Release Tag
Stable Commit
Development Branch
```

---

# 🗺 Roadmap

后续主要演进方向：

```text
Intent Understanding Accuracy
Capability Selection
Planner Strategy
Evaluation Feedback
Multimodal Agent
Tool / MCP Ecosystem
A2A Agent
Cross-task Workflow
Production Observability
Event Replay
Distributed Performance
Cross-host HA
Production Deployment
```

---

# 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

---

# 👨‍💻 Author

**Qin LingHang**

GitHub: [QinLingHang](https://github.com/QinLingHang)

如果这个项目对你的 Agent 开发与学习有所帮助，欢迎 Star ⭐
