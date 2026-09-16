AgentMesh
> 面向多用户、多项目的 Multi-Agent 应用与运行时平台｜Go 控制面 · Python Runtime · Kafka 可靠结果交付
AgentMesh 基于 Go Control Plane + Python Agent Runtime + React / TypeScript 构建，围绕 Multi-Agent 编排、多模态 RAG、Conversation Memory、Tool / MCP、分布式执行、故障恢复、多租户治理 等能力展开，并在 P21 引入 Kafka Event Plane + SQLite Durable Outbox，用于可靠交付 Agent 执行结果。
项目并非单一聊天页面或简单的模型 API 封装，而是尝试从 Agent Runtime、知识检索、长期会话、工具调用、任务可靠执行以及工程化部署等角度，构建一套完整的 Agent 应用运行体系。
已发布的稳定版本（Release / Tag）：
```text
v1.0.0
```
开发进度： P20 长会话可靠性已完成专项验收；P21 Kafka 结果交付改造已合并至 `main`，并通过 Windows 本地部署验收。不要据此推断这些能力已经包含在 `v1.0.0` Tag，或容器化生产发布已经验收。
---
✨ Features
Agent Runtime
支持 Agent 的动态发现、选择与协作执行。
主要能力：
Capability Discovery
Task Profile
Agent Resolver
Agent Routing
Serial Execution
Parallel Execution
DAG Multi-Agent Workflow
Runtime Rescheduling
Timeout / Failure Recovery
Execution Trace
AgentMesh 可以根据任务所需能力，以及 Agent 的：
Capability
Success Rate
Latency
Cost
Load
动态筛选并路由执行 Agent，降低 Agent 与固定 Workflow 之间的强绑定。
---
🤖 Multi-Agent Orchestration
Python Runtime 基于：
FastAPI
LangGraph
asyncio
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
🔍 Multimodal RAG
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
Document Knowledge
Image / Visual Knowledge
Chunking
Embedding
Vector Retrieval
Hybrid Retrieval
Rerank
Citation
RAG Gating
支持三种检索模式：
```text
TEXT
VISUAL
HYBRID
```
通过 RAG Gating 判断当前任务是否真正需要知识检索，避免无意义地向上下文注入大量内容。
检索得到的文本和视觉证据会统一进入 Agent Context，参与后续推理。
---
🧠 Conversation & Memory
AgentMesh 对 Conversation History 与 Runtime Memory 进行分层处理。
MySQL
负责持久化完整会话历史。
Redis
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
Conversation History
Historical Message Pagination
Working Memory
Context Budget
Memory Capsule
Context Compaction
Redis-loss Recovery
Long Conversation Continuity
P20 历史消息分页与首尾标记恢复、刷新后连续性校验
在 P20 自动化长会话测试中，已验证 125/125 历史消息完整恢复、分页可见锚点稳定、刷新后会话连续性与 Redis Memory 丢失后的恢复。
MySQL 中的 Durable History 是持久化依据；Redis Working Memory 可丢失并通过持久化历史恢复。上述结果属于已验证的测试场景，不表示任意规模或任意故障下的绝对保证。
---
🔧 Tool & MCP
AgentMesh 支持 Agent 调用内部 Tool、HTTP Tool 以及 MCP Tool。
主要能力：
Internal Tool
HTTP Tool
Tool Schema
Tool Discovery
Tool Invocation
MCP Discovery
MCP Invocation
Parameter Validation
Tool Governance
Approval
Tool Result Feedback
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
⚙️ Distributed Runtime
AgentMesh 针对 Multi-Worker Agent Runtime 实现了分布式任务执行与故障恢复机制。
主要包括：
Durable Queue
Worker Registration
Worker Heartbeat
Lease
Fencing Token
Idempotent Execution
Backpressure
Deadline
Cancel
Worker Recovery
Dispatcher Recovery
Task Reassignment
Lease / Fencing
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
RESULT_PENDING 与结果交付
P21 为“Agent 已计算完成、业务尚未确认结果”增加了 `RESULT_PENDING` 协调机制：Broker ACK 仅表示 Kafka 接收了消息，Business ACK 才表示 Go 已完成业务提交。 在业务确认前保留必要的执行归属，避免消费滞后被错误认定为 Worker 丢失。
---
📨 Kafka Event Plane & Durable Result Delivery（P21）
旧版结果链路依赖 Python 向 Go 发起 HTTP Callback；网络抖动或 Go 暂时不可达时，有限次 Retry 可能仍无法交付结果。P21 在保留 HTTP 兼容模式的同时，新增可恢复的异步结果通道。
```text
Go Durable Queue / Scheduler
            ↓ assignment (HTTP)
Python Worker → LLM / Tool / MCP → Result
            ↓ persist before publish
       SQLite Outbox
            ↓ publish / Broker ACK
  Kafka: agentmesh.runtime.events
            ↓ consumer group
      Go Result Consumer
            ↓ validate fence + deduplicate
  Business Finalization / MySQL
            ↓ Business ACK
  Release execution ownership
```
主要机制：
SQLite Durable Outbox：先持久化终态事件，再异步发送；Kafka 故障或 Python 进程重启后可恢复待投递记录（前提是 Outbox 文件可恢复）。
Broker ACK / Business ACK 分离：消息入 Kafka 不代表任务已完成；`RESULT_PENDING` 避免过早释放执行所有权。
At-Least-Once + 幂等消费：通过稳定 `event_id`、数据库处理记录与业务状态恢复，处理重复投递；业务提交后才推进 Kafka 消费位点。
Lease / Fencing：拒绝旧执行归属的结果；支持同一 Worker 在更高 fence 下重新执行。
DLQ 隐私保护：无法正常处理的消息可进入 DLQ，记录哈希、大小、来源位置及错误分类，不保存可逆的原始敏感消息。
HTTP Fallback：通过配置保留旧结果回调路径，便于兼容和故障排查。
Kafka 负责事件传输，原有 Go Durable Queue 仍负责任务调度；二者职责不同，不能相互替代。P21 已实际接入的核心业务是 Runtime Result。Tool / Model / Audit / Usage 等 Topic 具备基础配置，但不等于相应事件生产者和消费者已全部投入使用。
详细设计与验收合同：`docs/p21/P21_EVENT_DRIVEN_RUNTIME.md`、`docs/p21/CODEX_P21_VALIDATION.md`。
---
🔐 Multi-Tenant Governance
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
Organization
Workspace
Project
RBAC
Project Scope
Resource Ownership
BYOK
Secret Isolation
Knowledge Isolation
Conversation Isolation
Memory Isolation
Tool Governance
通过 User / Organization / Project Scope 对平台资源进行权限与归属校验，避免不同用户或项目之间出现数据串用。
---
🔑 Model Gateway & BYOK
AgentMesh 支持项目级模型配置以及 BYOK：
```text
Bring Your Own Key
```
模型访问通过统一的 Provider 层进行抽象，Runtime 不直接与单一模型厂商强绑定。
主要能力：
Model Provider
Project Model Configuration
BYOK
Secret Isolation
Usage Control
Governance Check
不同项目可以配置各自的 Model Provider 与访问凭据。
---
🌐 Platform Capability
除 Agent Runtime 外，AgentMesh 还提供部分平台化能力。
包括：
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
用于支持 Agent 能力复用以及第三方系统接入。
---
🖥️ Desktop Bridge
项目包含 Desktop Bridge，用于扩展 Agent 与本地桌面环境之间的交互能力。
当前主要能力包括：
Desktop Capability Discovery
Read-only Desktop Access
Tool Integration
Governance Check
Runtime Trace
Desktop 能力仍然遵循平台的 Project Scope 与 Governance 检查机制。
---
📊 Execution Trace & Observability
AgentMesh 提供 Agent 执行全过程追踪能力。
包括：
Execution Trace
Run Details
Task Profile
Scheduling Decision
Agent Execution
Tool Invocation
MCP Invocation
Failover Event
Runtime Error
Recovery Event
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
🏗 Architecture
AgentMesh 使用多语言分层架构：React/TypeScript 提供交互界面，Go 控制面处理身份、治理和持久任务调度，Python Runtime 执行 Agent。P21 额外引入独立的结果事件传输链路。
```text
React / TypeScript Web
       │ HTTP / SSE
       ▼
Nginx Gateway（部署可选；同源代理 / TLS）
       │
       ▼
Go Control Plane ────────────────► MySQL / Redis
  │ Auth / Registry / Governance      任务、会话、状态、缓存
  │ Durable Queue / Lease / Fence
  │
  └── HTTP assignment ─────────► Python Agent Runtime
                                │ LangGraph / RAG / Memory / Tool / MCP
                                ├──────────────► Milvus（向量检索）
                                │
                                ▼
                          SQLite Durable Outbox
                                │
                                ▼
                             Kafka
                                │ runtime events
                                ▼
                         Go Result Consumer
                                │ idempotency / fencing / finalize
                                └──────────────► MySQL
```
说明： MySQL/Redis 与 Python 的实际读写由具体模块决定，图中重点展示任务分发和结果回传。Windows 本地开发不要求启动 Nginx；Nginx 属于可选网关部署形态。Kafka 不是 Go 与 Python 之间所有 HTTP 的替代品。
---
🧩 Runtime Flow
一条采用 Kafka 结果传输的典型 Durable Agent 任务：
```text
User Request
   ↓
Go: Auth / Project Scope / Governance
   ↓
Go: Durable Queue → Dispatcher → Lease / Fencing
   ↓ HTTP assignment
Python Worker: Agent execution (RAG / Memory / Tool / MCP)
   ↓
Result generated → persist SQLite Outbox
   ↓
Kafka publish → Broker ACK
   ↓ (RESULT_PENDING while awaiting business completion)
Go Consumer: fence validation → event idempotency
   ↓
Finalize task / result / conversation in MySQL
   ↓
Business ACK → release execution ownership
   ↓
Task COMPLETED / UI displays final answer
```
如果 Kafka 暂时不可用，Outbox 保留待发送事件；如果 Go 消费者暂时不可用，Kafka 在保留策略内积压消息。重复投递需要通过业务幂等处理，不能仅依靠 Kafka 避免重复副作用。旧 HTTP Callback 仍为可选兼容模式。
---
🛠 Tech Stack
Backend
```text
Go
Gin
Python
FastAPI
Pydantic
asyncio
LangGraph
```
Frontend
```text
React
TypeScript
Vite
```
Storage & Messaging
```text
MySQL                   Durable history / business state
Redis                   Working memory / cache
Milvus                  Vector database
SQLite                  Python local durable result outbox
Apache Kafka 3.9.1      Runtime result event transport（开发 Compose）
```
Agent
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
Infrastructure
```text
Docker
Docker Compose
Nginx
JWT
SSE
RBAC
```
---
📁 Project Structure
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
│   ├── p21                 # Event Plane 设计、验收与发布说明
│   └── Architecture / Validation / Documentation
│
├── docker-compose.yml      # 开发基础设施（含 Kafka）
├── docker-compose.production.yml
├── docker-compose.v3-ha.yml
│
├── VERSION
├── MANIFEST.json
├── LICENSE
└── README.md
```
---
🚀 Quick Start
Requirements
准备 Go、Python、Node.js、Docker Desktop / Docker Compose。请按项目配置文件中的要求安装依赖，并为实际模型服务配置可用的 Provider；本地可靠性测试可以使用项目内置的确定性 Mock Provider。
```bash
git clone https://github.com/QinLingHang/AgentMesh.git
cd AgentMesh
```
Windows 本地开发（P21 已验收的部署形态）
```text
Windows 本机：Go Control Plane / Python Runtime / React
Docker Compose：MySQL / Redis / Kafka / Milvus / etcd / MinIO
Compose Project：agentmesh_runtime_mvp_full_v02
```
先打开 Docker Desktop，并确认当前目录的 `docker-compose.yml` 确实指向原有基础设施，再检查已有容器：
```powershell
docker compose -p agentmesh_runtime_mvp_full_v02 ps
```
初次启用 Kafka、且已核实使用这份 Compose 文件时，可按需启动 Kafka 与 Topic 初始化服务：
```powershell
docker compose -p agentmesh_runtime_mvp_full_v02 up -d kafka kafka-init
```
不要在共享开发环境随意执行 `docker compose down -v`，也不要以新的 Compose Project 名重复创建基础设施。`kafka-init` 创建完 Topic 后正常退出（exit 0）。
Go、Python 在 Windows 本机运行时，依据 `.env.example` 配置 Kafka：
```dotenv
# backend-go：启用 Go Kafka Runtime Consumer
KAFKA_ENABLED=true
KAFKA_BROKERS=127.0.0.1:29092

# runtime-python：启用 SQLite Outbox + Kafka Result Transport
RUNTIME_RESULT_TRANSPORT=kafka
KAFKA_BROKERS=127.0.0.1:29092
```
以上是两个模块各自的配置示例，不要把注释和两组配置直接当作一个共享 `.env`。在相应模块中完成数据库连接、Runtime 内部 API、模型服务与前端设置后，按项目现有启动文档启动 Windows 本地进程；这里不假设每个人的启动脚本、端口或凭据相同。
容器内 Kafka 地址通常为 `kafka:9092`，本机地址为 `127.0.0.1:29092`（以实际 Compose Listener 配置为准）。若需要旧回调模式，使用 `RUNTIME_RESULT_TRANSPORT=http` 并核对 Go/Python 对应的结果交付配置。
不要提交 `.env`、`runtime-python/data/`、SQLite Outbox、凭据或测试生成的数据文件。更完整的设计与校验步骤见 `docs/p21/`。
---
✅ Reliability Validation
AgentMesh 在开发过程中针对 Agent Runtime、分布式执行、长会话以及多租户场景进行了持续自动化验收。
既往阶段的部分验收结果（不同版本、不同测试范围；不能视为全部在同一次生产部署下验证）：
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

P21 Windows Local Deployment      FINAL PASS
Kafka Outage E2E (B/B2)           PASS
Outbox / Broker vs Business ACK   PASS
Same-worker Higher Fence          PASS
Successful Duplicate Idempotency PASS
Go Consumer Backlog Recovery      PASS
COMPLETING Crash Replay          21/21 PASS
HTTP Fallback                     PASS
DLQ Privacy / Offset-skip         PASS
Go readonly build (server/migrate) PASS
```
P21 验收环境为 Windows 本机 Go/Python/React + `agentmesh_runtime_mvp_full_v02` Docker 基础设施。该结论仅覆盖此部署形态；Go/Python 容器化构建、生产集群发布及海量吞吐压力测试尚未作为本次 P21 验收结论。
---
📦 Release
当前已发布的稳定版本：
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
Runtime Regression
Distributed Runtime Validation
Conversation History Validation
Memory Recovery Validation
Governance Validation
Browser E2E
Release Validator
Strict-tree Validation
Source Hygiene Validation
Security / Privacy Validation
版本状态：
```text
v1.0.0 Tag / Release: Stable Release
main: 已合并 P21；P20 以实际提交记录为准
```
P21 已通过 Windows 本地部署最终验收，但尚未据此发布新的正式版本或新 Tag；不要把 `v1.0.0` 下载包视为已包含 P21。
---
🎯 Project Goal
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

Agent 执行成功，但网络/Kafka/Go 故障时如何可靠交付结果？

消息重放时怎样避免重复写答案与旧 Worker 覆盖结果？
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
Event Delivery
```
AgentMesh 主要围绕这些问题进行实现。
---
🗺 Roadmap
AgentMesh 的已发布稳定基线是 `v1.0.0`；P20 已完成专项验收、P21 已合并至开发主线。后续演进以实际提交记录与真实测试结果为准。
后续如果继续演进，可能关注：
更丰富的 Agent Runtime Strategy
更完善的 Agent Evaluation
更强的 Multimodal Agent 能力
更多 MCP / Tool 生态接入
更完善的 Runtime Observability
更丰富的 Agent Template / Marketplace
将 Tool / Model / Audit / Usage 等 Kafka Topic 从基础配置逐步扩展为真实生产者与消费者
Kafka 多节点部署、容量规划、吞吐压测与容器化发布验收
`v1.0.0` Release 与后续 `main` 开发进度应分别查看，避免把未发布能力误认为已经包含在稳定发布包中。
---
📄 License
This project is licensed under the Apache License 2.0.
See:
```text
LICENSE
```
for details.
---
👨‍💻 Author
Qin LingHang
GitHub:
https://github.com/QinLingHang
---
如果这个项目对你的 Agent / Multi-Agent 学习有所帮助，欢迎 Star ⭐
