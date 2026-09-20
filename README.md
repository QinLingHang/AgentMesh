# AgentMesh

**Adaptive Multi-Agent Orchestration · Distributed Agent Runtime · AI Application Infrastructure**

面向多用户、多项目场景的 Agent 应用与运行时平台。

基于 **Go Control Plane + Python Agent Runtime + React / TypeScript** 构建，提供从语义任务规划、多 Agent 编排、知识检索、长期记忆、Tool / MCP 调用，到分布式执行、运行时恢复、可靠结果交付和多租户治理的完整工程实践。

[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](LICENSE)
![Go](https://img.shields.io/badge/Go-Control%20Plane-00ADD8)
![Python](https://img.shields.io/badge/Python-Agent%20Runtime-3776AB)
![React](https://img.shields.io/badge/React-TypeScript-149ECA)
![Kafka](https://img.shields.io/badge/Kafka-Event%20Plane-231F20)

---

## 📖 项目介绍

AgentMesh 是一个面向真实任务执行的 Agent 应用与运行时平台。

与简单的 LLM API 封装、固定 Workflow 或单 Agent Tool Loop 不同，AgentMesh 关注的是：

**如何理解复杂任务、动态拆解执行步骤、选择合适的 Agent、组织多个 Agent 协同工作，并在工具调用、远程 Agent、Worker 故障、结果交付异常和长会话等情况下保持执行过程可观测、可恢复和可治理。**

平台采用多语言分层架构：

| 模块 | 技术 | 核心职责 |
|:---|:---|:---|
| Control Plane | Go / Gin | API、认证、Durable Task、资源管理与治理 |
| Agent Runtime | Python / FastAPI / LangGraph | Semantic Planner、Multi-Agent、DAG、RAG、Memory、Tool / MCP |
| Web | React / TypeScript | Workspace、知识管理、执行详情与治理 |
| Storage | MySQL / Redis / Milvus | 业务持久化、运行时记忆与向量检索 |
| Event Plane | Kafka / SQLite Outbox | 执行结果可靠交付与异步事件传输 |

**项目核心目标：构建可规划、可协作、可观测、可恢复、可扩展的 Agent Runtime。**

---

## ✨ 核心功能

AgentMesh 主要围绕以下能力进行设计与实现。

| 能力模块 | 功能 |
|:---|:---|
| Adaptive Workflow | Semantic Planner、ExecutionPlan、Plan Validation、Plan Compiler |
| Multi-Agent | 动态发现、智能路由、Hybrid DAG、Fan-out / Fan-in、多 Agent 协作 |
| Agent Runtime | Internal / LangGraph / HTTP / A2A Agent 统一执行 |
| Runtime Recovery | Quality Gate、Repair、Reschedule、Replan |
| Multimodal RAG | 文本与视觉知识检索、混合检索和引用 |
| Memory | 长期记忆、上下文压缩、会话持久化与恢复 |
| Tool / MCP | 工具发现、参数校验、执行反馈与治理 |
| Distributed Runtime | Durable Queue、多 Worker、Lease、Fencing |
| Reliability | 幂等执行、故障恢复、Kafka 可靠结果交付 |
| Multi-Tenant | Organization、Workspace、RBAC、资源隔离 |
| Model Gateway | 多模型配置、BYOK、模型路由与密钥隔离 |
| Platform Ecosystem | Public API、SDK、Agent Template、Marketplace |
| Observability | Trace、Planner、DAG、调度决策、质量门控与故障诊断 |

---

# 🏗 系统架构

AgentMesh 将控制面、Agent Workflow、执行层和基础设施可靠性进行分层。

```text
                    ┌─────────────────────────┐
                    │   React / TypeScript    │
                    │                         │
                    │ Workspace / Run Details │
                    │ Knowledge / Governance  │
                    └────────────┬────────────┘
                                 │
                             HTTP / SSE
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │     Go Control Plane    │
                    │                         │
                    │ Auth / Organization     │
                    │ Agent / Tool Registry   │
                    │ Durable Task / API      │
                    │ RBAC / Governance       │
                    └────────────┬────────────┘
                                 │
                          Durable Dispatch
                                 │
                                 ▼
              ┌──────────────────────────────────┐
              │       Python Agent Runtime       │
              │                                  │
              │ Task Profile / Semantic Planner  │
              │ ExecutionPlan / Plan Validator   │
              │ Adaptive Scheduler               │
              │ Plan Compiler / Hybrid DAG       │
              │ DAGExecutor                      │
              │ Quality Gate / Recovery          │
              └────────────────┬─────────────────┘
                               │
              ┌────────────────┼─────────────────┐
              │                │                 │
              ▼                ▼                 ▼
        Internal Agent   LangGraph Agent    Remote Agent
                                             │
                                      ┌──────┴──────┐
                                      ▼             ▼
                                  HTTP Agent     A2A Agent
              │                │                 │
              └────────────────┼─────────────────┘
                               │
                        Tool / MCP / RAG
                        Memory / Model
                               │
                               ▼
                        Execution Result
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

### 架构设计

**Go Control Plane**

负责高并发 API、用户与项目管理、Durable Task、执行状态、权限治理、资源管理以及数据库持久化。

**Python Agent Runtime**

负责 Agent 的智能运行，包括任务分析、语义规划、ExecutionPlan、Agent Routing、Hybrid DAG、多 Agent 协作、质量门控、失败恢复、知识检索、记忆管理和 Tool / MCP 调用。

**LangGraph**

LangGraph 是 AgentMesh 支持的一种 Agent Executor，用于执行具备模型调用、工具循环和受限 Repair 能力的 Workflow Agent。

LangGraph 不负责 Durable Queue、Worker Lease、Fencing、Kafka Result Delivery 等基础设施级调度。

**React Web**

提供面向用户的 Agent Workspace，以及运行详情、知识管理、Memory、平台治理和执行过程观测界面。

**基础设施**

- MySQL：业务数据、会话历史和任务状态。
- Redis：缓存与 Runtime Working Memory。
- Milvus：向量存储及知识检索。
- Kafka：Runtime 结果事件的异步传输与消费恢复。

Go Durable Runtime 负责任务可靠调度，Python Agent Runtime 负责任务内部智能编排，Kafka 负责执行结果可靠交付，三者职责相互独立。

---

# 🤖 1. Adaptive Multi-Agent Orchestration

AgentMesh 支持基于用户 Query 的自适应任务规划与异构 Multi-Agent 编排。

简单任务可以继续走低开销 Fast Path；复杂任务则进入 Semantic Planner，由 Planner 将用户目标转换为带依赖关系的 ExecutionPlan。

### 核心执行链路

```text
User Query
    │
    ▼
Task Profile
    │
    ▼
Complexity Gate
    │
    ├──────── Simple Task
    │              │
    │              ▼
    │          Fast Path
    │
    └──────── Complex Task
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
       ┌───────────┼────────────┐
       ▼           ▼            ▼
   Internal     LangGraph    HTTP / A2A
    Agent        Agent         Agent
       │           │            │
       └───────────┼────────────┘
                   │
                   ▼
             Quality Gate
              │   │   │
           PASS REPAIR FAIL
              │   │   │
              │   │   └── Reschedule / Replan
              │   └────── Bounded Repair
              │
              ▼
            Synthesis
              │
              ▼
          Final Answer
```

---

## Semantic Planner

Semantic Planner 负责回答：

> **这个任务需要做什么？**

而不是直接决定具体由哪个 Agent 执行。

例如用户输入：

```text
分析系统架构和安全风险，
并根据两部分分析结果给出最终优化方案。
```

可以形成类似的 ExecutionPlan：

```text
Architecture Analysis ─┐
                       ├── Solution Design
Security Analysis ─────┘
```

其中每个 Step 可以包含：

```text
step id
objective
required capability
dependencies
execution metadata
```

Planner 只描述任务目标和能力需求。

真正的 Agent 仍由 Scheduler 根据 Registry、Capability、质量、可靠性、成本、延迟和负载情况进行选择。

因此 AgentMesh 保持：

```text
Planner   = What to do
Scheduler = Who executes
```

---

## Plan Validation

所有 Semantic Plan 在进入执行层之前都必须经过验证。

包括：

- Duplicate Step ID 检查
- Self Dependency 检查
- Missing Dependency 检查
- DAG Cycle 检查
- Step 数量限制
- Capability 合法性检查
- Planner 输出结构检查
- Replan 后再次 Validation

非法 Plan 不会直接进入 Agent 执行层。

Planner 出现超时、解析异常或非法结构时，可以根据任务类型进入 deterministic fallback 或 fail-closed 流程。

---

## Hybrid Dynamic DAG

AgentMesh 不再局限于固定的：

```text
single
parallel
sequential
```

还可以根据 ExecutionPlan 编译真正的混合依赖 DAG。

例如：

```text
          A ─────┐
                 ├──── C ────┐
          B ─────┘            │
               └──── D ──────┤
                              ▼
                              E
```

支持：

- Serial Dependency
- Parallel Ready Set
- Fan-out
- Fan-in
- Hybrid Dependency
- Conditional / Optional Execution
- Dependency-aware Scheduling

只有依赖已经满足的 Step 才会进入 Ready Set。

---

## Heterogeneous Agent Execution

同一个 ExecutionPlan 可以组合不同执行协议的 Agent。

当前支持：

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

不同 Agent 的执行结果可以根据 DAG Dependency 向下游 Step 传播。

因此 AgentMesh 的 Multi-Agent 并不是多个固定 Prompt 串联，而是：

**Semantic Planning + Capability Routing + Heterogeneous Agent Execution + Dynamic DAG。**

---

## Quality Gate & Runtime Recovery

Agent 执行完成后，Evaluation 不再只是生成一个评分。

Quality Gate 可以直接参与 Runtime 控制。

```text
Agent Result
     │
     ▼
 Evaluation
     │
     ▼
 Quality Gate
 ┌───┼─────────────┐
 │   │             │
PASS REPAIR       FAIL
 │   │             │
 │   ▼             ▼
 │ Same Agent   Reschedule
 │                │
 │                ▼
 │             Replan
 │                │
 └────────────────┘
        │
        ▼
      Finish
```

### Bounded Repair

对于明确安全的本地 Model-only Agent，当结果质量不足时，可以根据 Critique 进行有限次数的 Repair。

Repair 具备硬性次数限制，避免无限 Agent Loop。

### Runtime Reschedule

Agent 发生执行异常时，可以重新选择能力兼容的候选 Agent。

已明确失败且被排除的 Agent 不会被无限重复选择。

### Replan

当问题来自原始计划而不是单个 Agent 时，可以重新规划剩余任务：

```text
Original:

A → B → C

A completed
B failed

Replan:

A → X → B → C
```

已经成功执行的 `A` 不会因为 Replan 被重复执行。

---

## Side-Effect Replay Protection

AgentMesh 对可能产生副作用的执行采取更加严格的恢复策略。

已经完成的：

```text
Tool Action
HTTP Agent Action
A2A Agent Action
Approval-gated Action
```

不会因为单纯的质量评分不足而自动再次执行。

系统具备：

- Bounded Repair
- Bounded Replan
- Completed Step Carry-forward
- Completed Side-effect Carry-forward
- HTTP / A2A Replay Protection
- Tool Replay Protection

降低自动恢复过程中产生重复业务副作用的风险。

---

# 🔍 2. Multimodal RAG

AgentMesh 支持文本和视觉知识的检索增强生成。

### 知识处理流程

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
    Citation
       │
       ▼
  Agent Context
```

### 主要能力

- Document Knowledge
- Image / Visual Knowledge
- Chunking
- Embedding
- Vector Retrieval
- Hybrid Retrieval
- Rerank
- Citation
- RAG Gating

支持三种检索模式：

`TEXT` · `VISUAL` · `HYBRID`

通过 RAG Gating 判断当前任务是否需要知识检索，减少无关知识对 Agent 上下文的干扰。

检索得到的证据会统一进入 Agent Context，参与后续任务规划和执行。

---

# 🧠 3. Conversation & Memory

AgentMesh 将完整会话历史、长期 Memory、运行时 Working Memory 和 Project Knowledge 分层管理。

### 存储职责

| 组件 | 职责 |
|:---|:---|
| MySQL | 完整会话历史及业务持久化 |
| Redis | Runtime Working Memory |
| User Memory | User-global 长期记忆 |
| Memory Capsule | 长上下文压缩与记忆延续 |
| Milvus | Project-scoped 知识向量存储与检索 |

### 主要能力

- Conversation History
- Historical Message Pagination
- User-global Memory
- Working Memory
- Context Budget
- Memory Capsule
- Context Compaction
- Redis-loss Recovery
- Long Conversation Continuity

### Conversation History Reliability

针对长会话场景，AgentMesh 增强了历史分页、上下文恢复与持久化可靠性。

已验证：

- 125+ 历史消息持久恢复
- 历史分页可见锚点稳定
- 同一会话刷新后保留已展开历史
- Memory Capsule 恢复
- Redis Working Memory 丢失后的会话恢复

Memory 和 Knowledge 分别采用：

```text
Memory    → User-global
Knowledge → Project-scoped
```

避免不同项目之间出现非预期的知识串用。

---

# 🔧 4. Tool & MCP

AgentMesh 支持 Agent 发现和调用 Internal Tool、HTTP Tool 及 MCP Tool。

### 核心能力

- Internal Tool
- HTTP Tool
- Tool Schema
- Tool Discovery
- Tool Invocation
- MCP Discovery / Invocation
- Parameter Validation
- Tool Governance
- Human Approval
- Tool Result Feedback

### Tool 调用流程

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
 Agent Continue / Final
```

Tool Schema 用来描述模型可以使用哪些工具以及参数结构。

ToolCall 是模型根据 Schema 生成的结构化工具调用请求。

真正的工具执行由 Runtime / Tool Registry / MCP Adapter 完成，而不是由模型自身完成。

工具调用同时受到权限、项目归属、风险等级和 Human Approval 机制约束。

---

# ⚙️ 5. Distributed Agent Runtime

AgentMesh 针对多 Worker 场景实现了分布式执行与故障恢复机制。

### 核心能力

| 机制 | 作用 |
|:---|:---|
| Durable Queue | 持久化任务队列 |
| Worker Registration | Worker 注册与管理 |
| Heartbeat | Worker 存活检测 |
| Lease | 执行所有权管理 |
| Fencing | 防止旧 Worker 提交过期结果 |
| Idempotent Execution | 降低重复执行风险 |
| Backpressure | 负载控制 |
| Deadline / Cancel | 执行时限与取消控制 |
| Worker Recovery | Worker 故障恢复 |
| Dispatcher HA | 调度器高可用协调 |

### Lease 与 Fencing

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

当 Worker 失联或 Lease 过期时，系统可根据安全恢复策略重新分配任务。

旧 Worker 即使之后恢复，也不能凭借过期 Fencing Token 覆盖当前执行所有权对应的结果。

---

## Reliable Result Delivery

AgentMesh 使用 Kafka Event Plane 实现 Runtime 执行结果的可靠交付。

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

### 可靠性设计

- **Durable Outbox**：执行结果先落盘，再异步发送。
- **At-Least-Once**：允许消息重复投递，通过幂等处理避免重复业务提交。
- **RESULT_PENDING**：区分 Agent 已完成计算与结果尚未交付。
- **Broker ACK / Business ACK**：区分消息接收成功和业务处理完成。
- **Fencing Validation**：拒绝旧执行归属提交的结果。
- **Consumer Recovery**：支持积压消息恢复。
- **DLQ**：处理异常事件并限制敏感信息暴露。
- **HTTP Compatibility**：保留原有结果回调兼容模式。

Go Durable Queue 负责任务可靠调度，Kafka 负责执行结果交付，两者并不互相替代。

详细说明：[Event-Driven Runtime](docs/runtime/EVENT_DRIVEN_RUNTIME.md)

---

# 🔐 6. Multi-Tenant Governance

AgentMesh 面向多用户、多组织和多项目场景提供资源治理能力。

### 资源层级

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

### 核心能力

- Organization / Workspace
- RBAC
- Project Scope
- Resource Ownership
- BYOK Secret Isolation
- Knowledge Isolation
- Conversation Isolation
- Memory Isolation
- Quota / Usage
- Audit

Planner 和 Replanner 不能直接绕过 Registry / Scheduler 指定未经授权的 Agent。

所有 Agent、Tool、MCP、Knowledge 和 Model 能力仍受到现有 Project Scope 和 Governance 约束。

---

# 🔑 7. Model Gateway & BYOK

AgentMesh 通过统一的 Model Provider 抽象接入模型服务。

支持：

- 用户与项目模型配置
- Model Provider
- BYOK（Bring Your Own Key）
- 多 Provider Candidate
- 模型选择与路由
- Secret Isolation
- Usage Control
- Governance Check

Runtime 不直接绑定单一模型厂商。

用户可以根据项目需求配置自己的模型服务和访问凭据。

Adaptive Router 可以结合质量、可靠性、延迟、成本和运行状态进行模型选择。

---

# 🌐 8. Platform Ecosystem

除 Agent Runtime 外，AgentMesh 还提供平台化扩展能力。

主要包括：

- Public API
- API Key
- Service Account
- Python SDK
- TypeScript SDK
- Agent Template
- Agent Versioning
- Plugin Registry
- MCP Registry
- Marketplace

通过 Registry、SDK 和 API 支持 Agent 能力复用与第三方系统接入。

---

# 🖥️ 9. Desktop Bridge

项目包含 Desktop Bridge，用于扩展 Agent 与本地桌面环境之间的交互。

主要能力：

- Desktop Capability Discovery
- Read-only Desktop Access
- Tool Integration
- Governance Check
- Runtime Trace

桌面能力遵循平台权限与治理约束。

对本地环境产生修改的操作仍需遵循对应的风险与 Approval 规则。

---

# 📊 10. Execution Trace & Observability

AgentMesh 提供运行过程追踪能力，用于理解 Agent 的规划、执行行为和故障原因。

包括：

- Task Profile
- Semantic Planning
- Plan Validation
- DAG Compilation
- Scheduling Decision
- Agent Assignment
- Agent Execution
- Tool / MCP Invocation
- Quality Evaluation
- Repair
- Reschedule
- Replan
- Runtime Error
- Worker / Failover Event
- Kafka / Outbox 状态与相关计数
- Final Synthesis

支持分析：

- 为什么这个任务进入 Semantic Planner？
- Planner 将任务拆成了哪些 Step？
- Step 之间为什么存在依赖？
- 为什么选择当前 Agent？
- 当前任务由哪些 Agent 协作？
- 哪些 Step 可以并行？
- RAG 检索了哪些知识？
- Tool / MCP 调用是否成功？
- 为什么发生 Repair？
- 为什么重新选择 Agent？
- 为什么重新规划？
- 哪个 Worker 执行了任务？
- 任务失败后如何恢复？

最终回答与详细 Trace 分离展示，避免复杂执行细节干扰正常 Workspace 使用体验。

---

# 🛠 技术栈

| 层级 | 技术 |
|:---|:---|
| Frontend | React、TypeScript、Vite |
| Control Plane | Go、Gin |
| Agent Runtime | Python、FastAPI、LangGraph、asyncio |
| Database | MySQL |
| Cache / Memory | Redis |
| Vector Database | Milvus |
| Event Plane | Apache Kafka、SQLite Outbox |
| Infrastructure | Docker、Docker Compose、Nginx |
| Security | JWT、RBAC、BYOK |
| Communication | HTTP、SSE、Kafka、A2A |

---

# 📁 项目结构

```text
AgentMesh/
│
├── backend-go/          # Go Control Plane
│
├── runtime-python/      # Python Agent Runtime
│   └── app/
│       ├── planning/    # Semantic Planner / ExecutionPlan / Validator
│       ├── services/    # Scheduler / DAG / Runtime / Quality Gate
│       ├── agents/      # Internal / LangGraph / HTTP / A2A Executors
│       └── eval/        # Evaluation / Repair
│
├── web-react/           # React / TypeScript Web
├── desktop-bridge/      # Desktop Integration
├── sdk/                 # Python / TypeScript SDK
├── infra/               # Infrastructure
├── scripts/             # Test / Ops
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

各模块的配置、测试与技术说明可参考对应目录及 `docs/`。

---

# 🚀 快速开始

## 1. 环境要求

建议准备：

- Go
- Python
- Node.js
- Docker Desktop
- Docker Compose

## 2. 克隆项目

```bash
git clone https://github.com/QinLingHang/AgentMesh.git
cd AgentMesh
```

## 3. 启动基础设施

当前 Windows 本地开发环境采用：

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

检查基础设施状态：

```powershell
docker compose -p agentmesh_runtime_mvp_full_v02 ps
```

首次搭建请根据仓库 Compose 文件和环境配置启动依赖服务。

不要在已有数据的开发环境中随意执行：

```powershell
docker compose down -v
```

以避免删除持久化数据。

## 4. 配置服务

参考：

```text
backend-go/.env.example
runtime-python/.env.example
```

配置数据库、Redis、模型服务以及 Runtime 相关参数。

使用 Kafka 结果交付模式时，需要分别启用：

```text
Go Runtime Consumer
Python Kafka Result Transport
```

Adaptive Workflow 的 Planner、Quality Gate、Repair 和 Replan 参数可通过 Runtime 配置控制，并设置执行次数和恢复边界。

## 5. 启动应用

根据各模块配置分别启动：

- Go Control Plane
- Python Agent Runtime
- React Web

首次使用前需要完成数据库初始化和模型服务配置。

详细配置和测试说明请查看 `docs/`。

---

# ✅ 测试与验收

AgentMesh 针对 Runtime、Adaptive Workflow、记忆、分布式执行、治理和可靠性进行了持续自动化测试。

当前主分支关键回归结果：

| 验收范围 | 结果 |
|:---|:---|
| Adaptive Workflow Targeted | 61/61 PASS |
| Semantic Planner | PASS |
| Complex Chinese Planning | PASS |
| Plan Validation | PASS |
| Hybrid Dynamic DAG | PASS |
| Fan-out / Fan-in | PASS |
| Quality Gate | PASS |
| Bounded Repair | PASS |
| Reschedule | PASS |
| Replan | PASS |
| Completed Step Carry-forward | PASS |
| Side-effect Replay Protection | PASS |
| Mixed Internal / LangGraph / HTTP / A2A | PASS |
| Python Runtime Full Regression | 417/417 PASS |
| Go Control Plane Regression | PASS |
| React Contract Tests | 110/110 PASS |
| React Production Build | PASS |
| Python SDK | 3/3 PASS |
| TypeScript SDK | 3/3 PASS |
| Multimodal RAG | PASS |
| Tool / MCP | PASS |
| Distributed Runtime | PASS |
| Lease / Fencing | PASS |
| Conversation History Recovery | PASS |
| Memory Capsule / Redis-loss Recovery | PASS |
| Multi-Tenant Governance | PASS |
| Kafka Result Delivery | PASS |
| Duplicate Event Idempotency | PASS |
| Higher-Fence Recovery | PASS |
| COMPLETING Crash Replay | PASS |

### Adaptive Workflow Safety

已验证：

```text
Repair bounded: YES
Replan bounded: YES
Completed step replay prevented: YES
Completed side-effect replay prevented: YES
HTTP/A2A automatic quality replay prevented: YES
Tool automatic side-effect replay prevented: YES
```

### 架构边界验证

```text
Semantic Planner
→ ExecutionPlan
→ Scheduler
→ Plan Compiler
→ DAGExecutor
```

已验证成立。

同时：

```text
Planner = What to do
Scheduler = Who executes

LangGraph = Agent Executor
Durable Runtime = Infrastructure Reliability
Kafka = Result Delivery
```

职责保持独立。

### 验收范围说明

当前代码已通过 Windows 本地 Go / Python / React 与 Docker 基础设施环境下的自动化回归与可靠性验证。

真实生产 Kafka 集群、大规模并发性能、跨主机生产 HA 和完整云生产部署仍需要独立环境验收。

---

# 📦 Release

当前已发布版本：

**AgentMesh v1.0.0**

[查看 GitHub Releases](https://github.com/QinLingHang/AgentMesh/releases)

当前 GitHub `main` 已包含发布版本之后继续演进的能力，包括：

- Conversation Reliability
- Event-Driven Result Delivery
- Adaptive Semantic Multi-Agent Workflow

因此：

**Release Tag 表示对应历史稳定发布范围，`main` 表示当前持续演进中的最新源码。**

使用时请以对应 Tag、Commit 和 Release Notes 为准。

---

# 🗺 Roadmap

后续演进方向：

- 增强 Planner 与 Evaluation 的策略学习和长期反馈闭环。
- 扩展更丰富的 Multimodal Agent 能力。
- 扩展 Tool / MCP / A2A 与 Agent 生态。
- 完善跨任务 Workflow 模板与可复用 Agent Graph。
- 增强 Kafka 事件体系、事件回放与运行时诊断。
- 增强 Production Observability 与故障分析能力。
- 进行更大规模 Multi-Agent 并发与性能压测。
- 完成更完整的容器化生产部署与跨主机 HA 验证。

---

# 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

---

# 👨‍💻 Author

**Qin LingHang**

GitHub: [QinLingHang](https://github.com/QinLingHang)

如果这个项目对你的 Agent 开发与学习有所帮助，欢迎 Star ⭐
