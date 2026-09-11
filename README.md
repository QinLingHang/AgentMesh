# AgentMesh

> 面向多用户、多项目场景的 Multi-Agent 应用与运行时平台

AgentMesh 是一个基于 **Go Control Plane + Python Agent Runtime + React / TypeScript** 构建的 Agent 应用平台，围绕 **Multi-Agent 编排、多模态 RAG、Conversation Memory、Tool / MCP、分布式执行、故障恢复以及多租户治理** 等能力进行实现。

项目并非单一聊天页面或简单的模型 API 封装，而是尝试从 Agent Runtime、知识检索、长期会话、工具调用、任务可靠执行以及工程化部署等角度，构建一套完整的 Agent 应用运行体系。

当前稳定版本：

```text
v1.0.0
```

---

## ✨ Features

### Agent Runtime

支持 Agent 的动态发现、选择与协作执行。

主要能力：

- Capability Discovery
- Task Profile
- Agent Resolver
- Agent Routing
- Serial Execution
- Parallel Execution
- DAG Multi-Agent Workflow
- Runtime Rescheduling
- Timeout / Failure Recovery
- Execution Trace

AgentMesh 可以根据任务所需能力，以及 Agent 的：

- Capability
- Success Rate
- Latency
- Cost
- Load

动态筛选并路由执行 Agent，降低 Agent 与固定 Workflow 之间的强绑定。

---

## 🤖 Multi-Agent Orchestration

Python Runtime 基于：

- FastAPI
- LangGraph
- asyncio

实现 Multi-Agent Runtime。

支持串行、并行以及 DAG 形式的 Agent 协作。

基本执行流程：

```text
User Task
    ↓
Task Profile
    ↓
Capability Discovery
    ↓
Agent Resolver
    ↓
Multi-Agent DAG
    ↓
Runtime Execution
    ↓
Failure / Timeout
    ↓
Runtime Rescheduling
    ↓
Final Result
```

当 Agent 在执行过程中出现 Timeout / Failure 时，可以重新选择能力兼容的 Agent 接替任务，实现运行时故障恢复。

---

## 🔍 Multimodal RAG

AgentMesh 内置知识检索链路，支持文本与视觉知识。

主要流程：

```text
Document / Image
       ↓
 Knowledge Ingest
       ↓
     Chunking
       ↓
    Embedding
       ↓
      Milvus
       ↓
Hybrid Retrieval
       ↓
     Rerank
       ↓
    Citation
       ↓
  Agent Context
```

主要能力：

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

```text
TEXT
VISUAL
HYBRID
```

通过 RAG Gating 判断当前任务是否真正需要知识检索，避免无意义地向上下文注入大量内容。

检索得到的文本和视觉证据会统一进入 Agent Context，参与后续推理。

---

## 🧠 Conversation & Memory

AgentMesh 对 Conversation History 与 Runtime Memory 进行分层处理。

### MySQL

负责持久化完整会话历史。

### Redis

负责保存 Runtime Working Memory。

整体结构：

```text
Conversation
    ↓
MySQL Durable History
    +
Redis Working Memory
    ↓
Context Budget
    ↓
Memory Capsule
    ↓
Agent Runtime
```

主要能力：

- Conversation History
- Historical Message Pagination
- Working Memory
- Context Budget
- Memory Capsule
- Context Compaction
- Redis-loss Recovery
- Long Conversation Continuity

在自动化长会话测试场景中完成：

```text
125 / 125 历史消息完整恢复
```

即使 Runtime Redis Memory 丢失，仍可基于持久化会话数据恢复上下文，保证长会话连续性。

---

## 🔧 Tool & MCP

AgentMesh 支持 Agent 调用内部 Tool、HTTP Tool 以及 MCP Tool。

主要能力：

- Internal Tool
- HTTP Tool
- Tool Schema
- Tool Discovery
- Tool Invocation
- MCP Discovery
- MCP Invocation
- Parameter Validation
- Tool Governance
- Approval
- Tool Result Feedback

基本调用链：

```text
Agent
  ↓
Tool Discovery
  ↓
Schema Injection
  ↓
Model Decision
  ↓
Tool Invocation
  ↓
Governance Check
  ↓
Execution
  ↓
Tool Result
  ↓
Agent Continue
```

Tool / MCP 的执行结果会重新注入 Agent Context，驱动 Agent 继续完成后续推理和任务执行。

---

## ⚙️ Distributed Runtime

AgentMesh 针对 Multi-Worker Agent Runtime 实现了分布式任务执行与故障恢复机制。

主要包括：

- Durable Queue
- Worker Registration
- Worker Heartbeat
- Lease
- Fencing Token
- Idempotent Execution
- Backpressure
- Deadline
- Cancel
- Worker Recovery
- Dispatcher Recovery
- Task Reassignment

### Lease / Fencing

通过：

```text
Lease + Fencing Token
```

控制 Worker 的任务执行所有权。

基本过程：

```text
Task
  ↓
Durable Queue
  ↓
Worker Acquire Lease
  ↓
Generate Fencing Token
  ↓
Execute Task
  ↓
Commit Result
```

当 Worker 超时或失联后，任务可以重新分配给新的 Worker。

旧 Worker 即使之后恢复，也无法使用过期的 Fencing Token 覆盖新 Worker 已提交的执行结果，从而降低重复执行及脏写风险。

---

## 🔐 Multi-Tenant Governance

AgentMesh 支持多用户、多组织以及多项目资源治理。

主要资源层级：

```text
User
  ↓
Organization
  ↓
Workspace / Project
  ↓
Agent
Knowledge
Conversation
Memory
Model
Tool
MCP
```

主要能力：

- Organization
- Workspace
- Project
- RBAC
- Project Scope
- Resource Ownership
- BYOK
- Secret Isolation
- Knowledge Isolation
- Conversation Isolation
- Memory Isolation
- Tool Governance

通过 User / Organization / Project Scope 对平台资源进行权限与归属校验，避免不同用户或项目之间出现数据串用。

---

## 🔑 Model Gateway & BYOK

AgentMesh 支持项目级模型配置以及 BYOK：

```text
Bring Your Own Key
```

模型访问通过统一的 Provider 层进行抽象，Runtime 不直接与单一模型厂商强绑定。

主要能力：

- Model Provider
- Project Model Configuration
- BYOK
- Secret Isolation
- Usage Control
- Governance Check

不同项目可以配置各自的 Model Provider 与访问凭据。

---

## 🌐 Platform Capability

除 Agent Runtime 外，AgentMesh 还提供部分平台化能力。

包括：

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

用于支持 Agent 能力复用以及第三方系统接入。

---

## 🖥️ Desktop Bridge

项目包含 Desktop Bridge，用于扩展 Agent 与本地桌面环境之间的交互能力。

当前主要能力包括：

- Desktop Capability Discovery
- Read-only Desktop Access
- Tool Integration
- Governance Check
- Runtime Trace

Desktop 能力仍然遵循平台的 Project Scope 与 Governance 检查机制。

---

## 📊 Execution Trace & Observability

AgentMesh 提供 Agent 执行全过程追踪能力。

包括：

- Execution Trace
- Run Details
- Task Profile
- Scheduling Decision
- Agent Execution
- Tool Invocation
- MCP Invocation
- Failover Event
- Runtime Error
- Recovery Event

可以用于分析：

```text
为什么选择这个 Agent？

当前任务被拆成了什么结构？

RAG 检索到了什么内容？

Agent 调用了什么 Tool / MCP？

哪个 Worker 执行了任务？

为什么发生 Runtime Rescheduling？

任务失败以后如何恢复？

最终结果来自哪一条执行链路？
```

---

# 🏗 Architecture

AgentMesh 整体采用：

```text
Go Control Plane
        +
Python Agent Runtime
        +
React / TypeScript Web
```

的多语言分层结构。

整体通信关系如下：

```text
┌──────────────────────────────────────────────┐
│              React / TypeScript              │
│                   Web UI                     │
│                                              │
│ Workspace / Chat / Knowledge / Run Details   │
└──────────────────────┬───────────────────────┘
                       │
                       │ HTTP / SSE
                       ▼
┌──────────────────────────────────────────────┐
│                Nginx Gateway                 │
│                                              │
│ Same-Origin API / Reverse Proxy / TLS        │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│               Go Control Plane               │
│                                              │
│ Auth / User / Organization / Project         │
│ Agent Registry / Model Registry              │
│ Tool Registry / MCP Registry                 │
│ RBAC / Governance / BYOK                     │
│ Task Control / Public API                    │
└──────────────────────┬───────────────────────┘
                       │
                       │ Internal API
                       ▼
┌──────────────────────────────────────────────┐
│             Python Agent Runtime             │
│                                              │
│ LangGraph                                    │
│ Task Profile                                 │
│ Capability Discovery                         │
│ Agent Resolver                               │
│ Multi-Agent DAG                              │
│ Runtime Rescheduling                         │
│ Multimodal RAG                               │
│ Conversation Memory                          │
│ Tool / MCP                                   │
│ Execution Trace                              │
└──────────────┬──────────────┬────────────────┘
               │              │
               │              │
       ┌───────▼───────┐      └───────────────┐
       │ MySQL / Redis │                      │
       │               │                      ▼
       │ Conversation  │               ┌──────────────┐
       │ Working Memory│               │    Milvus    │
       │ Runtime State │               │              │
       │ Governance    │               │ Vector Store │
       └───────────────┘               │ Multimodal   │
                                       │     RAG      │
                                       └──────────────┘
```

---

# 🧩 Runtime Flow

一次典型 Agent 请求大致经过：

```text
User Request
     ↓
Go Control Plane
     ↓
Auth / Project Scope / Governance
     ↓
Python Agent Runtime
     ↓
Task Profile
     ↓
Capability Discovery
     ↓
Agent Resolver
     ↓
Multi-Agent DAG
     ↓
┌──────────┬──────────┬──────────┐
│   RAG    │  Memory  │ Tool/MCP │
└──────────┴──────────┴──────────┘
     ↓
Runtime Execution
     ↓
Worker / Durable Queue
     ↓
Failure?
 ┌───┴────┐
 │        │
No       Yes
 │        ↓
 │   Rescheduling
 │        ↓
 └──────► Continue
          ↓
      Final Result
          ↓
    Conversation Store
          ↓
      Execution Trace
```

---

# 🛠 Tech Stack

## Backend

```text
Go
Gin
Python
FastAPI
Pydantic
asyncio
LangGraph
```

## Frontend

```text
React
TypeScript
Vite
```

## Storage

```text
MySQL
Redis
Milvus
```

## Agent

```text
Multi-Agent
LangGraph
RAG
Memory
Tool Calling
MCP
Capability Discovery
Agent Routing
Runtime Rescheduling
Execution Trace
```

## Infrastructure

```text
Docker
Docker Compose
Nginx
JWT
SSE
RBAC
```

---

# 📁 Project Structure

```text
AgentMesh
├── backend-go
│   └── Go Control Plane
│
├── runtime-python
│   └── Python Agent Runtime
│
├── web-react
│   └── React / TypeScript Web
│
├── desktop-bridge
│   └── Desktop Integration
│
├── infra
│   └── Infrastructure / Docker Compose
│
├── scripts
│   ├── Test
│   ├── Release
│   └── Ops
│
├── docs
│   └── Architecture / Validation / Documentation
│
├── VERSION
├── MANIFEST.json
├── LICENSE
└── README.md
```

---

# 🚀 Quick Start

## Requirements

建议准备以下环境：

```text
Go
Python
Node.js
Docker
Docker Compose
```

---

## Clone

```bash
git clone https://github.com/QinLingHang/AgentMesh.git

cd AgentMesh
```

---

## Project Modules

项目主要由以下模块组成：

```text
backend-go
runtime-python
web-react
desktop-bridge
infra
```

启动项目前建议首先查看：

```text
docs/
infra/
```

根据对应环境配置启动：

```text
MySQL
Redis
Milvus
```

并完成 Model Provider、数据库、Runtime 以及 Gateway 等相关配置。

---

# ✅ Reliability Validation

AgentMesh 在开发过程中针对 Agent Runtime、分布式执行、长会话以及多租户场景进行了持续自动化验收。

部分最终验证结果：

```text
Conversation History Recovery     PASS
125 / 125 Message Recovery        PASS
Memory Capsule                    PASS
Redis-loss Recovery               PASS

Durable Queue                     PASS
Worker Heartbeat                  PASS
Lease / Fencing                   PASS
Idempotent Execution              PASS
Worker Recovery                   PASS
Dispatcher Recovery               PASS

Multi-Agent Runtime               PASS
Runtime Rescheduling              PASS
Multimodal RAG                    PASS
Tool / MCP                        PASS

Multi-Tenant Isolation            PASS
Governance                        PASS

Browser E2E                       PASS
Release Validator                 PASS
Strict-tree Validation            PASS
```

---

# 📦 Release

当前稳定版本：

```text
AgentMesh v1.0.0
```

Git Tag：

```text
v1.0.0
```

Release Source：

```text
AgentMesh_v1.0.0_SOURCE.zip
```

`v1.0.0` 已完成：

- Runtime Regression
- Distributed Runtime Validation
- Conversation History Validation
- Memory Recovery Validation
- Governance Validation
- Browser E2E
- Release Validator
- Strict-tree Validation
- Source Hygiene Validation
- Security / Privacy Validation

当前版本状态：

```text
Stable Release
```

---

# 🎯 Project Goal

AgentMesh 的目标并不是简单封装一个 LLM Chat API。

这个项目更关注：

```text
Agent 如何理解任务？

Agent 如何发现能力？

Agent 如何选择执行 Agent？

多个 Agent 如何协作？

Agent 如何获得外部知识？

文本和图片知识如何统一检索？

Agent 如何保存长期上下文？

Agent 如何调用真实工具？

Worker 故障以后任务如何继续执行？

如何避免旧 Worker 重复提交结果？

Redis Memory 丢失以后会话如何恢复？

不同用户和项目的数据如何真正隔离？

复杂 Agent 执行过程如何调试与追踪？
```

对于一个完整 Agent 系统而言，模型调用只是其中一个环节。

真正复杂的工程问题往往集中在：

```text
State
Context
Memory
RAG
Tool
Idempotency
Recovery
Isolation
Scheduling
Governance
Observability
```

AgentMesh 主要围绕这些问题进行实现。

---

# 🗺 Roadmap

AgentMesh `v1.0.0` 已完成当前阶段的核心能力建设。

后续如果继续演进，可能关注：

- 更丰富的 Agent Runtime Strategy
- 更完善的 Agent Evaluation
- 更强的 Multimodal Agent 能力
- 更多 MCP / Tool 生态接入
- 更完善的 Runtime Observability
- 更丰富的 Agent Template / Marketplace

当前仓库以 `v1.0.0` 稳定版本为主。

---

# 📄 License

This project is licensed under the **Apache License 2.0**.

See:

```text
LICENSE
```

for details.

---

# 👨‍💻 Author

**Qin LingHang**

GitHub:

https://github.com/QinLingHang

---

如果这个项目对你的 Agent / Multi-Agent 学习有所帮助，欢迎 Star ⭐
