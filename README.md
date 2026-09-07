# AgentMesh

> 面向多用户、多项目、多模型场景的开源 Agent 应用平台。  
> 基于 **Go + Python + React + TypeScript** 构建，覆盖 Agent Runtime、Multi-Agent、RAG、Memory、Tool、MCP、BYOK、RBAC、可观测性、分布式执行与生产部署。

**当前公开版本：** `v1.0.0-rc.2`  
**当前开发版本：** `2.0.0-dev`（V2 Intelligence & Multimodal Sprint，未发布）  
**开源协议：** Apache License 2.0  
**项目状态：** V2 开发中；在计划能力全部完成并通过全量验收前不发布新的 Release

---

## 项目简介

AgentMesh 是一个面向真实 Agent 应用场景设计的多 Agent 平台。

它并不是简单地把大模型封装成一个聊天接口，而是围绕真实工程场景，逐步构建一套完整的 Agent 应用基础设施：

```text
用户请求
   ↓
身份 / 项目 / 权限校验
   ↓
Agent Runtime
   ↓
任务理解与能力分析
   ↓
Agent / Model Routing
   ↓
RAG / Memory / Tool / MCP
   ↓
DAG / Multi-Agent Execution
   ↓
Evaluation / Observability
   ↓
最终回答
```

AgentMesh 采用：

```text
Go Control Plane
        +
Python Agent Runtime
        +
React / TypeScript Frontend
```

的分层架构。

其中：

- **Go**：负责认证、用户、会话、项目、组织、权限、治理、任务控制以及 Runtime 调用；
- **Python**：负责 Agent、RAG、Memory、Tool、MCP、模型网关、智能路由、DAG、评测和分布式执行；
- **React + TypeScript**：提供 Workspace、Agent、知识库、Memory、模型设置、治理中心、任务管理以及 Run Details；
- **MySQL / Redis / Milvus**：分别承担结构化数据、缓存与状态、向量检索等基础能力。

AgentMesh 希望解决的不只是：

> “怎么调用一次大模型？”

而是：

> “一个真正面向多用户、多项目、可扩展、可治理、可观测的 Agent 应用平台应该如何设计？”

---

## 核心能力

### 1. Agent Runtime

AgentMesh 将 AI 执行能力独立到 Python Runtime。

Runtime 当前包含：

- Agent Capability Profile
- Agent Resolver
- Agent Workflow
- LangGraph Workflow
- DAG Execution
- Collaboration Planner
- A2A Discovery
- A2A Execution
- Runtime Context
- Task Resume
- Execution Trace
- Adaptive Routing
- Evaluation
- Distributed Execution

业务控制面和 AI Runtime 之间保持清晰职责边界：

```text
Go
负责“谁可以执行、执行什么、资源属于谁”

Python
负责“任务应该怎么执行”
```

### 2. Multi-Agent 编排

对于复杂任务，Runtime 可以根据任务能力需求选择合适的 Agent，并构建执行流程。

典型链路：

```text
Task
 ↓
Task Profiling
 ↓
Capability Analysis
 ↓
Agent Resolver
 ↓
Collaboration Planner
 ↓
Execution DAG
 ↓
Agent Execution
 ↓
Result Aggregation
 ↓
Final Answer
```

系统不仅支持单 Agent 执行，也为串行 Agent、并行 Agent、多步骤 DAG、Agent 协作、Agent 能力发现和可恢复任务执行提供 Runtime 基础。

---

## RAG 与知识库

### 3. Knowledge Base

AgentMesh 提供知识库能力，用于将用户或项目知识接入 Agent Runtime。

目前包括：

- Knowledge Base
- Document Parsing
- Document Ingestion
- Chunking
- Embedding
- Milvus Vector Search
- Hybrid Retrieval
- Query Intelligence
- Adaptive RAG Routing
- Reranker
- Evidence Provenance
- Citation Projection
- Citation Validation
- Grounded Answer Guard
- Multi-modal Knowledge（V2 development）
- Visual Evidence（V2 development）
- TEXT / VISUAL / HYBRID Retrieval（V2 development）
- Vision Provider / VLM Routing（V2 development）

RAG 并不是每次请求都无条件执行。Runtime 会根据任务特征判断是否真的需要知识检索。

```text
User Query
    ↓
Query Intelligence
    ↓
RAG Gating
    ↓
Hybrid Retrieval
    ↓
Rerank
    ↓
Evidence
    ↓
Context Builder
    ↓
Model
    ↓
Citation Validation
    ↓
Final Answer
```

这样可以减少无意义检索带来的额外延迟、Context 浪费、无关知识干扰和回答质量下降。

---

## Memory

### 4. 短期与长期 Memory

AgentMesh 将聊天历史和长期 Memory 分离。

#### 短期 Memory

主要用于当前 Session：

- Conversation Context
- Redis Memory
- Recent Messages
- Context Budget
- Session State

#### 长期 Memory

用于保存真正值得跨会话使用的信息：

- Automatic Memory Write
- Long-term Memory
- Memory Retrieval
- Memory Injection
- Memory Forget
- Memory Management
- Memory Observability

Memory 并不是简单地“把所有聊天记录永久保存”，而是通过相应策略判断：

```text
这条信息是否应该成为长期记忆？
```

同时对 Secret、Password、Token、API Key、Private Key 等敏感内容进行限制。

---

## Tool Runtime

### 5. Tool Execution

AgentMesh 支持 Agent 调用真实工具完成任务。

目前 Tool Runtime 包括：

- Internal Tool
- HTTP Tool
- Built-in Tool
- Tool Registry
- Tool Loop
- Tool Governance
- Secure Action
- Approval
- Calculator

工具执行流程：

```text
Agent
 ↓
Tool Selection
 ↓
Tool Registry
 ↓
Governance
 ↓
Approval（如需要）
 ↓
Tool Execution
 ↓
Observation
 ↓
Agent
```

对于具有副作用的操作，可以通过 Governance 与 Approval 控制 Agent 的执行边界。

---

## MCP

### 6. Model Context Protocol

AgentMesh 支持 MCP（Model Context Protocol）。

Runtime 中目前包括：

- MCP Client
- MCP Manager
- MCP Contract
- MCP Mapping
- MCP Retry / Backoff
- MCP Demo Server
- MCP Tool Integration

```text
Agent Runtime
      ↓
MCP Manager
      ↓
MCP Client
      ↓
External MCP Server
      ↓
Tools / Resources
```

AgentMesh 将显式 Tool Execution 与 MCP Discovery 区分开来。即使任务不需要 MCP Discovery，用户显式配置的 Internal / HTTP Tool 仍然可以独立执行。

---

## Model Gateway

### 7. 多模型与 BYOK

AgentMesh 将模型访问统一封装到 Model Gateway。

目前包括：

- Model Provider
- Model Gateway
- Model Runtime
- Model Routing
- Adaptive Model Routing
- Project Model Configuration
- User Model Configuration
- BYOK

BYOK：

```text
Bring Your Own Key
```

允许用户配置自己的模型 API Key。

因此平台可以逐步支持：

```text
不同用户
   ↓
不同 Provider
   ↓
不同 API Key
   ↓
不同 Model
   ↓
不同 Project Policy
```

敏感模型凭据不会作为普通业务字段直接暴露给前端。

---

## Governance

### 8. Organization / Project Governance

AgentMesh 提供组织与项目级治理能力。

核心资源关系：

```text
User
 │
 ├── Personal Project
 │
 └── Organization
        │
        ├── Members
        │
        └── Projects
```

目前包括：

- Organization
- Organization Member
- Project
- Organization / Project Binding
- Project Runtime
- RBAC
- Project Governance
- Tool Governance
- MCP Governance
- BYOK Governance

这使 AgentMesh 不再只面向单用户 Demo，而是开始具备团队、组织和项目维度的资源治理模型。

---

## 多租户隔离

### 9. Tenant Isolation

AgentMesh 将多租户隔离作为重要设计边界。

隔离维度包括：

- User
- Organization
- Project
- Session
- Knowledge Base
- Memory
- Model Configuration
- Tool
- MCP
- Runtime Resource

后端不会只依赖前端传入的资源 ID，而是结合 User Scope、Organization Scope、Project Scope 进一步判断资源归属。

项目同时提供 Tenant Isolation 测试脚本，用于验证关键租户边界。

---

## Distributed Runtime

### 10. 分布式执行

AgentMesh 已实现面向分布式 Runtime 的基础能力。

目前包括：

- Durable Queue
- Worker Registration
- Worker Heartbeat
- Lease
- Fencing
- Idempotent Execution
- Capacity
- Backpressure
- Deadline
- Cancellation
- Safe Retry Boundary
- Worker Recovery
- Dispatcher Recovery
- Circuit Breaker
- Graceful Shutdown

任务执行不再只依赖单进程内存状态，而是逐步演进为：

```text
Control Plane
      ↓
Durable Queue
      ↓
Dispatcher
      ↓
Worker Pool
      ↓
Agent Runtime
```

为后续 Worker 横向扩展和更高并发场景提供基础。

---

## Evaluation

### 11. Agent Evaluation

AgentMesh 内置 Agent Evaluation 能力。

目前包括：

- Eval Dataset
- Baseline
- Scorecard
- Runtime Evaluation
- Routing Evaluation
- Execution Metrics

项目中保留部分 Eval Case：

```text
runtime-python/evals/
```

用于验证不同 Runtime 策略的行为是否发生回归。

---

## Observability

### 12. Run Details

AgentMesh 将“最终回答”和“执行过程”分离。

Workspace 主要用于正常任务交互，而详细执行信息进入独立的 Run Details。

目前包括：

- Overview
- Execution Timeline
- Agent DAG
- Tool / MCP Trace
- RAG Trace
- Memory Trace
- Routing Trace
- Reliability Trace
- Eval Scorecard
- Run Health
- Feedback

这样既可以保持 Workspace 相对干净，又能为开发者提供完整的 Agent 调试信息。

---

## 前端

### 13. React + TypeScript

前端采用：

```text
React
TypeScript
Vite
```

主要功能页面包括：

- 登录 / 注册
- Workspace
- Session
- Agent 管理
- Knowledge Center
- Memory Center
- Tool
- MCP
- Model Settings
- Governance
- Tasks
- Run Details

UI 以中文作为主要界面语言。技术专有名词例如 Agent、Runtime、RAG、MCP、Memory、DAG、Trace、BYOK 保留英文表达。

---

## 系统架构

### 14. 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│                    React + TypeScript                       │
│                         Frontend                            │
│                                                             │
│ Workspace / Agent / Knowledge / Memory / Governance         │
│ Model Settings / Tasks / Run Details                        │
└────────────────────────────┬────────────────────────────────┘
                             │
                         HTTP / SSE
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Go Control Plane                         │
│                                                             │
│ Auth / User / Session                                       │
│ Organization / Project                                      │
│ Governance / RBAC                                           │
│ Tool / MCP Registry                                         │
│ Model Configuration                                         │
│ Task Control                                                │
│ Tenant Isolation                                            │
└────────────────────────────┬────────────────────────────────┘
                             │
                      Runtime Request
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Python Agent Runtime                     │
│                                                             │
│ Agent / LangGraph / DAG                                     │
│ Multi-Agent Collaboration                                   │
│ RAG / Knowledge                                             │
│ Memory                                                      │
│ Tool / MCP                                                  │
│ Model Gateway                                               │
│ Adaptive Routing                                            │
│ Evaluation                                                  │
│ Observability                                               │
│ Distributed Runtime                                         │
└───────────────┬────────────────┬────────────────┬────────────┘
                │                │                │
                ▼                ▼                ▼
              MySQL            Redis            Milvus
```

---

## 技术栈

### 15. Technology Stack

| 模块 | 技术 |
|---|---|
| Control Plane | Go |
| Agent Runtime | Python |
| Runtime API | FastAPI |
| Agent Workflow | LangGraph |
| Frontend | React + TypeScript |
| Frontend Build | Vite |
| Relational Database | MySQL |
| Cache / Session | Redis |
| Vector Database | Milvus |
| Container | Docker |
| Orchestration | Docker Compose |
| Gateway | Nginx |
| Communication | HTTP / SSE |
| Tool Protocol | MCP |
| Python Testing | Pytest |
| Go Testing | Go Test |
| Frontend Testing | Node Contract Test / Browser E2E |

---

## 项目目录

### 16. Repository Structure

```text
AgentMesh/
│
├── backend-go/
│   ├── cmd/
│   │   ├── server/
│   │   └── migrate/
│   ├── internal/
│   │   ├── cache/
│   │   ├── config/
│   │   ├── db/
│   │   ├── handler/
│   │   ├── middleware/
│   │   ├── model/
│   │   ├── repository/
│   │   ├── router/
│   │   ├── runtime/
│   │   ├── security/
│   │   ├── service/
│   │   ├── storage/
│   │   └── verification/
│   ├── scripts/
│   └── Dockerfile
│
├── runtime-python/
│   ├── app/
│   │   ├── agents/
│   │   ├── distributed/
│   │   ├── eval/
│   │   ├── kernel/
│   │   ├── knowledge/
│   │   ├── mcp/
│   │   ├── memory/
│   │   ├── models/
│   │   ├── optimization/
│   │   ├── plugins/
│   │   ├── rag/
│   │   ├── services/
│   │   └── tools/
│   ├── evals/
│   ├── examples/
│   ├── scripts/
│   ├── tests/
│   └── Dockerfile
│
├── web-react/
│   ├── e2e/
│   ├── src/
│   │   ├── components/
│   │   ├── features/
│   │   └── styles/
│   ├── tests/
│   └── Dockerfile
│
├── infra/
│   ├── gateway/
│   └── mysql/
│
├── scripts/
│   ├── ops/
│   └── release/
│
├── docs/
│
├── docker-compose.yml
├── docker-compose.production.yml
├── .env.auth-session.example
├── .env.production.example
├── .gitattributes
├── .gitignore
├── LICENSE
├── MANIFEST.json
├── README.md
└── VERSION
```

---

## 快速开始

### 17. 环境要求

建议准备：

```text
Go
Python 3
Node.js
npm
Docker
Docker Compose
```

基础设施主要包括：

```text
MySQL
Redis
Milvus
```

实际版本要求请以各子项目配置文件和 Docker 配置为准。

### 18. Python Runtime

```bash
cd runtime-python
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux / macOS：

```bash
source .venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

启动：

```bash
uvicorn app.main:app --reload
```

### 19. Go Backend

```bash
cd backend-go
go mod download
go run ./cmd/server
```

运行测试：

```bash
go test ./...
```

### 20. React Frontend

```bash
cd web-react
npm install
npm run dev
```

运行测试：

```bash
npm test
```

生产构建：

```bash
npm run build
```

---

## Docker

### 21. Docker Compose

项目根目录提供：

```text
docker-compose.yml
docker-compose.production.yml
```

开发环境可根据实际配置启动：

```bash
docker compose up -d
```

生产部署应根据 `.env.production.example` 创建实际运行环境配置。

请勿将真实的 `.env`、`.env.production`、API Key、JWT Secret、SMTP Password、TLS Private Key 提交到 Git 仓库。

---

## 环境变量

### 22. Environment

仓库提供若干 example 文件：

```text
.env.auth-session.example
.env.production.example
backend-go/.env.example
backend-go/.env.auth.smtp.example
runtime-python/.env.example
```

这些文件仅用于描述需要配置哪些环境变量，不应写入真实生产 Secret。

推荐流程：

```text
Example Config
      ↓
Copy
      ↓
Local / Production Config
      ↓
Secret Management
```

---

## 测试体系

### 23. Python

```bash
cd runtime-python
pytest -q
```

### 24. Go

```bash
cd backend-go
go test ./...
```

### 25. Frontend

```bash
cd web-react
npm test
npm run build
```

项目还包含 Browser E2E、Session Restore E2E、Smoke Test、Tenant Isolation Test、Runtime Contract Test、Release Validation，用于验证关键工程链路。

---

## 安全设计

### 26. Security Boundary

AgentMesh 当前重点考虑以下安全边界：

**Authentication**

- JWT Authentication
- Session Restore
- Authentication Middleware

**Authorization**

- RBAC
- Organization Scope
- Project Scope
- User Scope

**Secret**

- BYOK Secret Protection
- Environment Secret Isolation
- Memory Secret Rejection
- Sensitive Configuration Exclusion

**Agent Action**

- Tool Governance
- MCP Governance
- Secure Action
- Approval

**Data**

- Tenant Isolation
- Runtime Data Isolation
- Knowledge Scope
- Memory Scope

**Release**

- Forbidden File Scan
- Runtime Data Scan
- Local Path Scan
- Secret / Privacy Review
- Manifest Validation
- Archive Validation

---

## Release

### 27. 当前版本

当前公开 Release：

```text
AgentMesh v1.0.0-rc.2
```

该版本属于 Release Candidate，主要用于：

```text
Open Source Validation
        ↓
Cloud Staging
        ↓
Public Environment Validation
        ↓
v1.0.0
```

### 28. v1.0.0-rc.2 本地验收状态

在进入公开仓库之前，当前 Release Candidate 已完成本地工程验证，包括：

```text
Go Regression
Python Runtime Regression
React Contract Tests
React Build
Browser E2E
Session Restore
Organization Governance
Distributed Runtime
Release Packaging
Manifest Validation
Archive Validation
Open-source Hygiene
```

源码发布包同时进行了：

```text
Forbidden File Scan
Runtime Data Scan
Local Absolute Path Scan
Archive Integrity Validation
SHA-256 Validation
```

> `v1.0.0-rc.2` 当前仍属于 Release Candidate。云端 Staging、公网 HTTPS 以及真实公网环境中的完整业务链路将在后续阶段继续验证。

---

## Source Integrity

### 29. MANIFEST

源码快照中包含 `MANIFEST.json`。

MANIFEST 用于记录源码文件的：

```text
Relative Path
File Size
SHA-256
```

对于当前 `2.0.0-dev` 开发快照，它仅用于验证 **development source handoff** 的文件完整性，并不代表新的公开 Release，也不会改变已冻结的 `v1.0.0-rc.2` Tag、ZIP 或其 SHA-256。最终正式发布时会重新生成对应正式版本的 Release Manifest。

---

## 开源仓库原则

### 30. 不提交运行时数据

以下类型数据不应进入 Git：

```text
.env
node_modules
.venv
__pycache__
dist
logs
tmp
backup
TLS Private Key
Runtime Uploads
Knowledge Runtime Data
User Attachments
Local Database
```

相关规则已经写入 `.gitignore`，仓库同时通过 `.gitattributes` 管理跨平台换行行为。

---

## 文档

### 31. Documentation

项目技术文档位于：

```text
docs/
```

主要覆盖：

- Overall Architecture
- Memory Architecture
- Tool / MCP
- Evaluation
- Adaptive Routing
- Distributed Runtime
- Governance
- Production
- Release
- Security Boundary

推荐首先阅读：

```text
docs/ARCHITECTURE.md
docs/TESTING.md
docs/NEXT_ROADMAP.md
```

---

## Roadmap

### 32. 当前开发路线

AgentMesh 已暂停继续发布小版本。当前公开的 `v1.0.0-rc.2` 保持冻结，后续开发在未发布分支持续推进，待计划能力整体完成、全量回归和云端验收通过后再统一发布正式版本。

**V2 — Intelligence & Multimodal Sprint（当前）**

- Multi-modal RAG
- PDF / Image Knowledge
- Vision Runtime
- TEXT / VISUAL / HYBRID Retrieval
- Multi-modal Citation
- Advanced Evaluation
- LLM-as-a-Judge
- Regression Dataset
- Token / Cost Accounting
- Advanced Observability

当前 V2 开发源码已进入整体验收准备阶段，但在 Python / Go / React / Browser E2E / Privacy 等强制 Gate 全部取得真实 PASS 前，不标记为正式完成版本。

**V3 — Distributed Runtime Sprint**

- Worker Horizontal Scaling
- Multi-node Runtime
- Capacity-aware Scheduling
- Failover / Recovery
- High Availability
- Distributed Observability

**V4 — Platform Ecosystem Sprint**

- Public API / API Key
- Python SDK
- Agent Marketplace
- Agent Versioning / Installation
- MCP / Plugin Registry
- Permission Governance

**Final Production Closure**

- Cloud Multi-node Deployment
- HTTPS / Domain
- Real Browser E2E
- Security / Privacy / Recovery
- Load / Capacity Validation
- Clean Source Packaging
- Final Release

---

## 为什么做 AgentMesh

很多 Agent 项目可以快速完成：

```text
Prompt
  ↓
LLM
  ↓
Tool
  ↓
Answer
```

但当系统开始面对多个用户、多个项目、多个模型、多个 Agent、多个 Tool、多个 MCP Server、知识库、长期 Memory、权限、任务恢复、高并发、分布式 Worker、可观测性和生产部署之后，问题就不再只是“如何写 Prompt”，而会逐渐演变成：

```text
Runtime 如何设计？
资源如何隔离？
Agent 如何路由？
工具如何治理？
Memory 如何控制？
任务如何恢复？
失败如何重试？
模型如何切换？
执行过程如何观测？
系统如何扩展？
```

AgentMesh 的核心目标，就是围绕这些问题持续进行工程实践。

---

## 项目定位

AgentMesh 当前更偏向：

```text
Agent Infrastructure
+
Agent Application Platform
+
AI Backend Engineering
```

而不是一个只负责展示聊天效果的 AI Demo。

项目重点关注：

- Agent Runtime
- AI Application Architecture
- Backend Engineering
- Multi-Agent
- RAG
- Memory
- Tool / MCP
- Model Gateway
- Governance
- Distributed System
- Observability
- Production Readiness

---

## Contribution

### 33. 贡献

AgentMesh 当前仍处于早期开放阶段。

欢迎通过以下方式参与项目：

- Issue
- Pull Request
- Architecture Discussion
- Bug Report
- Feature Proposal

在提交代码前，建议至少完成对应模块测试。

---

## License

### 34. Apache License 2.0

AgentMesh 基于 **Apache License 2.0** 开源。

详情请参阅 `LICENSE`。

---

## Disclaimer

### 35. 使用说明

AgentMesh 当前公开版本仍为 `v1.0.0-rc.2` Release Candidate；`2.0.0-dev` 仅代表未发布开发源码，不是新的公开 Release。

在用于真实生产环境之前，请根据实际业务场景进一步完成：

- 安全审计
- Secret Management
- HTTPS
- 数据备份
- 日志治理
- Runtime Resource Limit
- Monitoring
- Alert
- High Availability
- Disaster Recovery
- Provider Quota Control
- Cost Control

任何生产部署都应使用独立的正式环境配置和 Secret 管理方案。

---

## AgentMesh

```text
Build Agents.
Connect Tools.
Govern Runtime.
```

**面向真实工程场景构建可扩展、可治理、可观测的 Agent Runtime。**
