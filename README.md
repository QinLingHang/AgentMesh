# AgentMesh

**Multi-Agent Platform · Distributed Agent Runtime · AI Application Infrastructure**

面向多用户、多项目场景的 Agent 应用与运行时平台。

基于 **Go Control Plane + Python Agent Runtime + React / TypeScript** 构建，提供从 Agent 编排、知识检索、记忆管理、工具调用到分布式执行、可靠性保障和多租户治理的完整工程实践。

[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](LICENSE)
![Go](https://img.shields.io/badge/Go-Control%20Plane-00ADD8)
![Python](https://img.shields.io/badge/Python-Agent%20Runtime-3776AB)
![React](https://img.shields.io/badge/React-TypeScript-149ECA)
![Kafka](https://img.shields.io/badge/Kafka-Event%20Plane-231F20)

---

## 📖 项目介绍

AgentMesh 是一个面向真实任务执行的 Agent 应用平台。

与简单的 LLM API 封装或固定 Workflow 不同，AgentMesh 关注的是：如何让多个 Agent 在复杂任务中发现能力、动态协作、访问知识、调用工具，并在网络异常、Worker 故障和长会话等情况下保持系统可靠运行。

平台采用多语言分层架构：

| 模块 | 技术 | 核心职责 |
|:---|:---|:---|
| Control Plane | Go / Gin | API、认证、任务调度、资源管理与治理 |
| Agent Runtime | Python / FastAPI / LangGraph | Agent 编排、RAG、Memory、Tool / MCP |
| Web | React / TypeScript | Workspace、知识管理、执行详情与治理 |
| Storage | MySQL / Redis / Milvus | 业务持久化、运行时记忆与向量检索 |
| Event Plane | Kafka / SQLite Outbox | 执行结果可靠交付与异步事件传输 |

**项目核心目标：构建可观测、可恢复、可扩展的 Agent 运行平台。**

---

## ✨ 核心功能

AgentMesh 主要围绕以下能力进行设计与实现。

| 能力模块 | 功能 |
|:---|:---|
| Multi-Agent | 动态发现、智能路由、串并行与 DAG 协作 |
| Agent Runtime | 任务规划、执行控制、失败恢复与重新调度 |
| Multimodal RAG | 文本与视觉知识检索、混合检索和引用 |
| Memory | 长期记忆、上下文压缩、会话持久化与恢复 |
| Tool / MCP | 工具发现、参数校验、执行反馈与治理 |
| Distributed Runtime | Durable Queue、多 Worker、Lease、Fencing |
| Reliability | 幂等执行、故障恢复、Kafka 可靠结果交付 |
| Multi-Tenant | Organization、Workspace、RBAC、资源隔离 |
| Model Gateway | 多模型配置、BYOK、模型路由与密钥隔离 |
| Platform Ecosystem | Public API、SDK、Agent Template、Marketplace |
| Observability | Trace、执行详情、调度决策、故障诊断 |

---

# 🏗 系统架构

AgentMesh 将控制面、运行时、前端和基础设施进行分层。

```text
                    ┌───────────────────────┐
                    │   React / TypeScript  │
                    │                       │
                    │ Workspace / Run Detail│
                    │ Knowledge / Governance│
                    └───────────┬───────────┘
                                │
                            HTTP / SSE
                                │
                                ▼
                    ┌───────────────────────┐
                    │    Go Control Plane   │
                    │                       │
                    │ Auth / Organization   │
                    │ Agent / Tool Registry │
                    │ Task / Scheduler      │
                    │ RBAC / Governance     │
                    └───────────┬───────────┘
                                │
                         Durable Queue
                         HTTP Dispatch
                                │
                                ▼
                    ┌───────────────────────┐
                    │  Python Agent Runtime │
                    │                       │
                    │ Agent / DAG / Planner │
                    │ RAG / Memory          │
                    │ LLM / Tool / MCP      │
                    │ Multi-Worker          │
                    └───────────┬───────────┘
                                │
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

负责高并发 API、用户与项目管理、任务调度、执行状态、权限治理以及数据库持久化。

**Python Agent Runtime**

负责 Agent 的智能运行，包括模型调用、多 Agent 协作、知识检索、记忆管理、工具调用和执行过程管理。

**React Web**

提供面向用户的 Agent Workspace，以及运行详情、知识管理和平台治理界面。

**基础设施**

- MySQL：业务数据、会话历史和任务状态。
- Redis：缓存与 Runtime Working Memory。
- Milvus：向量存储及知识检索。
- Kafka：Runtime 结果事件的异步传输与消费恢复。

Go 的 Durable Queue 负责任务调度，Kafka 负责执行结果交付，两者并不互相替代。

---

# 🤖 1. Multi-Agent Orchestration

AgentMesh 支持基于任务需求的 Agent 动态发现、选择与协作执行。

### 核心能力

- Task Profile
- Capability Discovery
- Agent Resolver
- Agent Routing
- Serial Execution
- Parallel Execution
- DAG Multi-Agent Workflow
- Runtime Rescheduling

典型执行过程：

```text
User Task
    │
    ▼
Task Profile
    │
    ▼
Capability Discovery
    │
    ▼
Agent Resolver
    │
    ▼
Multi-Agent DAG
    │
    ▼
Runtime Execution
    │
    ▼
Final Result
```

平台可以结合 Agent 的能力、成功率、延迟、成本和负载等信息进行动态路由。

当执行过程中出现失败或超时时，可在满足安全恢复条件的情况下重新选择能力兼容的 Agent，避免整个任务完全依赖固定执行路径。

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

检索得到的证据会统一进入 Agent Context，参与后续任务执行。

---

# 🧠 3. Conversation & Memory

AgentMesh 将完整会话历史、运行时工作记忆和知识库进行分层管理。

### 存储职责

| 组件 | 职责 |
|:---|:---|
| MySQL | 完整会话历史持久化 |
| Redis | Runtime Working Memory |
| Memory Capsule | 长上下文压缩与记忆延续 |
| Milvus | 项目知识向量存储与检索 |

### 主要能力

- Conversation History
- Historical Message Pagination
- Working Memory
- Context Budget
- Memory Capsule
- Context Compaction
- Redis-loss Recovery
- Long Conversation Continuity

### Conversation History Reliability
针对长会话场景，AgentMesh 增强了历史分页、上下文恢复与持久化可靠性。

已通过的关键验收包括：

- 125/125 历史消息恢复
- 历史分页可见锚点稳定
- 同一会话刷新后保留已展开历史
- Memory Capsule 恢复
- Redis Memory 丢失后的会话恢复

Memory 和 Knowledge 分别采用用户级全局记忆与项目级知识隔离机制，避免不同项目之间出现非预期的知识串用。

---

# 🔧 4. Tool & MCP

AgentMesh 支持 Agent 发现和调用内部工具、HTTP 工具及 MCP 工具。

### 核心能力

- Internal Tool
- HTTP Tool
- Tool Schema
- Tool Discovery
- Tool Invocation
- MCP Discovery / Invocation
- Parameter Validation
- Tool Governance
- Approval
- Tool Result Feedback

### 调用流程

```text
Agent
  │
  ▼
Tool Discovery
  │
  ▼
Schema Validation
  │
  ▼
Governance Check
  │
  ▼
Tool Invocation
  │
  ▼
Tool Result
  │
  ▼
Agent Continue
```

工具执行结果会重新进入 Agent Context，支持 Agent 根据真实工具反馈继续推理和执行。

工具调用同时受到权限、项目归属与治理机制约束。

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

在现有分布式 Runtime 基础上引入 Kafka，实现 Agent 执行结果的可靠交付。

```text
Python Agent
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
- **At-Least-Once**：允许消息重复投递，通过幂等处理防止重复业务副作用。
- **RESULT_PENDING**：区分 Agent 已完成计算与结果尚未交付。
- **Broker ACK / Business ACK**：区分消息接收成功和业务处理完成。
- **Fencing Validation**：拒绝旧执行归属提交的结果。
- **Consumer Recovery**：支持积压消息恢复。
- **DLQ**：处理异常事件并限制敏感信息暴露。
- **HTTP Fallback**：保留原有回调兼容模式。

已通过 Windows 本地部署可靠性验收。

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

平台通过权限与资源归属校验，降低不同用户、组织和项目之间发生越权访问与数据串用的风险。

---

# 🔑 7. Model Gateway & BYOK

AgentMesh 通过统一的 Model Provider 抽象接入模型服务。

支持：

- 用户与项目模型配置
- Model Provider
- BYOK（Bring Your Own Key）
- 模型选择与路由
- Secret Isolation
- Usage Control
- Governance Check

Runtime 不直接绑定单一模型厂商。

用户可以根据项目需求配置模型服务和访问凭据。

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

桌面能力遵循平台权限与治理约束，不意味着浏览器可以直接获取任意本地执行权限。

---

# 📊 10. Execution Trace & Observability

AgentMesh 提供运行过程追踪能力，用于理解 Agent 的执行行为和故障原因。

包括：

- Execution Trace
- Run Details
- Task Profile
- Scheduling Decision
- Agent Execution
- Tool / MCP Invocation
- Runtime Error
- Failover / Recovery Event
- Kafka / Outbox 状态与相关计数

支持分析：

- 为什么选择当前 Agent？
- 当前任务由哪些 Agent 协作？
- RAG 检索了哪些知识？
- 工具调用是否成功？
- 哪个 Worker 执行了任务？
- 为什么发生重新调度？
- 任务失败后如何恢复？

最终回答与详细执行信息分别展示，避免 Trace 干扰正常的 Workspace 使用体验。

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
| Communication | HTTP、SSE、Kafka |

---

# 📁 项目结构

```text
AgentMesh/
│
├── backend-go/          # Go Control Plane
├── runtime-python/      # Python Agent Runtime
├── web-react/           # React / TypeScript Web
├── desktop-bridge/      # Desktop Integration
├── sdk/                 # SDK
├── infra/               # Infrastructure
├── scripts/             # Test / Release / Ops
├── docs/                # Architecture / Validation
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

不要在已有数据的开发环境中随意执行 `docker compose down -v`。

## 4. 配置服务

参考：

```text
backend-go/.env.example
runtime-python/.env.example
```

配置数据库、Redis、模型服务以及 Runtime 相关参数。

使用 Kafka 结果交付模式时，需要分别启用 Go Consumer 和 Python Kafka Transport。

## 5. 启动应用

根据各模块配置分别启动：

- Go Control Plane
- Python Agent Runtime
- React Web

首次使用前需要完成数据库初始化和模型服务配置。

详细配置和验收说明请查看 `docs/`。

---

# ✅ 测试与验收

AgentMesh 在不同开发阶段针对 Runtime、记忆、分布式执行、治理和可靠性进行了持续测试。

| 验收范围 | 结果 |
|:---|:---|
| Multi-Agent Runtime | PASS |
| Multimodal RAG | PASS |
| Tool / MCP | PASS |
| Distributed Runtime | PASS |
| Lease / Fencing | PASS |
| Conversation History Recovery | PASS |
| Memory Capsule / Redis-loss Recovery | PASS |
| Multi-Tenant Governance | PASS |
| Browser E2E | PASS |
| Conversation History Reliability | PASS |
| Kafka Outage Recovery | PASS |
| Duplicate Event Idempotency | PASS |
| Higher-Fence Recovery | PASS |
| COMPLETING Crash Replay | 21/21 PASS |
| Windows Local Deployment | FINAL PASS |

**验收范围说明：**

已通过 Windows 本地 Go/Python + Docker 基础设施环境的可靠性验收。

Docker 容器化生产发布、真实生产 Kafka 集群和大规模并发性能仍需独立验收。

---

# 📦 Release

当前已发布版本：

**AgentMesh v1.0.0**

[查看 GitHub Releases](https://github.com/QinLingHang/AgentMesh/releases)


当前仓库代码与历史 Release 包的功能范围可能不同，请以对应 Tag、Commit 和发布说明为准。

---

# 🗺 Roadmap

后续演进方向：

- 完善 Agent Evaluation 与 Runtime Observability。
- 扩展 Multimodal Agent 能力。
- 增强 Tool / MCP 与 Agent 生态。
- 进一步完善 Kafka 事件体系与事件回放。
- 完成容器化生产发布及高并发性能验证。

---

# 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

---

# 👨‍💻 Author

**Qin LingHang**

GitHub: [QinLingHang](https://github.com/QinLingHang)

如果这个项目对你的 Agent 开发与学习有所帮助，欢迎 Star ⭐
