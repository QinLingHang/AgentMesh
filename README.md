AgentMesh
> 面向多用户、多项目的 Agent 应用与分布式运行平台。以 **Go Control Plane + Python Agent Runtime + React / TypeScript** 为核心，围绕 Multi-Agent 编排、RAG、Memory、Tool / MCP、多租户治理与可靠执行开展工程实践。
![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)
![Go](https://img.shields.io/badge/Backend-Go-00ADD8)
![Python](https://img.shields.io/badge/Runtime-Python-3776AB)
![React](https://img.shields.io/badge/Frontend-React%20%2B%20TypeScript-149ECA)
![Kafka](https://img.shields.io/badge/Event%20Plane-Apache%20Kafka-231F20)
AgentMesh 不只是模型 API 的聊天封装。项目将用户与项目管理、任务控制、Agent 执行、知识与记忆、工具调用以及运行状态分别放在明确的架构边界中，并通过持久化队列、Lease / Fencing、SQLite Outbox 和 Kafka 处理分布式执行中的失败与结果交付问题。
版本与验收边界： GitHub 已发布的 Release / Tag 为 `v1.0.0`；`main` 中后续合并了 V2 / V3 / V4 / V4.1、P20 与 P21 等开发成果。P21 已通过 Windows 本地部署验收，不等于包含 P21 的新版 Release 已发布，也不等于容器化生产发布或海量并发压测通过。 仓库根目录的 `VERSION` / `MANIFEST.json` 不能单独作为最新开发功能已发布的依据。
---
核心能力
领域	已实现的主要内容
Agent Runtime	任务画像、能力发现、Agent Resolver、模型路由、串行 / 并行 / DAG 执行、失败处理与执行追踪
Multi-Agent	按任务能力选择 Agent、协作规划、DAG 执行、运行时重新调度
RAG	文档与图片知识处理、Embedding、Milvus、混合检索、Rerank、证据来源与引用、TEXT / VISUAL / HYBRID 模式
Conversation & Memory	MySQL 持久会话、分页历史、Redis 工作记忆、上下文预算、Memory Capsule、历史恢复
Tool / MCP	工具注册、Schema、发现与调用、调用结果回填、治理与高风险操作审批
Model & BYOK	模型 Provider 抽象、个人模型服务池、任务级自动 / 手动选择、项目模型回退与凭据隔离
Distributed Runtime	MySQL Durable Queue、Worker / Node 心跳、容量调度、Lease / Fencing、Dispatcher HA、安全重试与故障恢复
Kafka Event Plane	SQLite Durable Outbox、Runtime Result 事件、Go Consumer、幂等账本、DLQ、Broker ACK / Business ACK
Governance	Organization / Workspace / Project、RBAC、资源归属、多租户隔离、配额与审计
Platform Ecosystem	Public API、API Key / Service Account、Python / TypeScript SDK、Agent Template / Version、Marketplace、插件与 MCP Registry
Observability	Run Details、DAG / Trace、路由、RAG、Memory、Tool / MCP、可靠性事件及部分用量 / 评测指标
Desktop Agent	本地文件、注册应用与 CLI 工具；可选的受控 Windows Computer Use 与独立 Desktop Bridge
这些能力并非都在同一版本中首次发布；请结合 `docs/`、相应模块源码和下文的验收范围理解。
架构与职责
```text
React / TypeScript Web          Python / TypeScript SDK
         |                                |
         +--------- HTTP / SSE ----------+
                          |
                    Go Control Plane
           Auth / Project / RBAC / BYOK
           Registry / Public API / Task
                 /       |         \
                /        |          \
       MySQL / Redis   Durable Queue    Governance / Audit
                         |
                  Go Dispatcher
                         | HTTP dispatch
                         v
                  Python Workers
           Agent / DAG / LLM / RAG /
             Memory / Tool / MCP
                         |
                  执行完成并产出结果
                         |
                SQLite Durable Outbox
                         |
                  Kafka Runtime Topic
                         |
                  Go Result Consumer
                         |
             幂等 / Fencing / Finalize
                         |
                MySQL Task / Result
                         |
                 Business ACK
                         |
             Python 释放执行归属
```
Go： 用户、组织与项目、权限、任务状态、持久队列与调度、数据库事务、Kafka 结果消费。
Python： Agent 运行、模型与路由、RAG / Memory、Tool / MCP、Worker 心跳、结果 Outbox 与 Kafka 发布。
React / TypeScript： Workspace、会话、知识与记忆管理、模型设置、治理、任务管理及独立的 Run Details。
MySQL / Redis / Milvus： 分别承载权威业务记录、工作记忆及缓存、向量检索。
Kafka： 结果事件的异步传输与消费进度管理，不替代 Go 的 MySQL Durable Queue 或浏览器 HTTP / SSE。
开发环境与生产 Compose 的部署拓扑不同，详见下文。
---
Agent 执行与智能能力
Multi-Agent 编排
Python Runtime 包含任务画像、Capability Discovery、Agent Resolver、协作规划、DAG Executor 和 Rescheduler。它可以按能力及运行指标选择候选 Agent，执行串行或并行步骤，并在符合安全条件时重新调度。多 Agent 协作指任务规划与编排，不表示多个大模型能够无约束地自主互相调用。
Multimodal RAG
知识摄取和查询链路涉及文档 / 图片解析、文本与视觉证据、Embedding、Milvus、Hybrid Retrieval、Rerank、Citation 与检索门控。查询可按 `TEXT`、`VISUAL` 或 `HYBRID` 选择证据；文本任务不应强制依赖视觉模型。Go 负责知识生命周期与 Scope，Python 负责摄取、检索和运行时上下文组装。
Conversation 与 Memory
MySQL 保存完整会话与消息，Redis 提供工作记忆；Context Budget、Compaction 与 Memory Capsule 用于长上下文管理。P20 实现了历史消息分页、旧消息加载、会话刷新与 Redis 丢失后的上下文恢复。
Scope 必须区分： User-global Memory 属于用户；Project Knowledge 属于项目。共享项目不会自动共享项目拥有者的用户级长期记忆，也不会把 RAG 证据、工具输出或项目 Secret 无条件写入用户级 Memory。
Tool、MCP 与 Desktop
Tool Runtime 支持内部工具、HTTP 工具、Schema 校验、执行结果回填与审批；MCP 集成包含发现与调用。Desktop Agent 通过受控能力接入本地文件、注册应用和 CLI 工具。可选 Computer Use 具有独立会话、权限与审批边界；高级终端默认关闭。单独的 `desktop-bridge/` 可作为受限回环服务，Windows 本地 Runtime 也有嵌入式 Desktop 能力。这些功能不代表浏览器能直接获得任意本机执行权限。
Model Gateway、BYOK 与 Evaluation
模型层提供 Provider 抽象、请求级模型选择、重试 / 超时和 Token / 成本元数据。个人模型池支持自动路由或显式选取；符合策略时可回退至项目配置。项目密钥按既有治理边界加密保存，不作为全局 Runtime Provider 共享。Evaluation 提供确定性评分、可选 Model Judge、数据集回归和 Run Details 相关指标；未知价格不会被凭空估算为真实账单。
---
分布式可靠性：Durable Runtime 与 Kafka
任务调度与结果交付是两件不同的事：
Go 将 Task 和 Runtime Job 保存到 MySQL Durable Queue，再由 Dispatcher 选择 Worker，通过内部 HTTP 分配执行。
Worker 使用 `execution_id`、`lease_token`、`fence_epoch` 等标识执行归属。过期 Worker 的结果不能覆盖新归属；对接受状态不确定的任务，不会无条件重放副作用。
Kafka 模式下，Python 完成计算后先将结果写入本地 SQLite Outbox，再投递 `agentmesh.runtime.events`。
Broker ACK 仅代表 Kafka 收到消息；Go Consumer 仍需验证归属与幂等，并完成业务持久化。
`RESULT_PENDING` 保留已经产出结果但尚未完成业务确认的状态。Go 通过精确归属匹配的终态确认让 Python 释放执行记录，避免因消费延迟误判 Worker 丢失。
消费者在成功处理或成功转交 DLQ 后才提交相应 Kafka offset。重复事件通过 `eventId` 去重，崩溃重放走既有 Callback 状态机恢复路径。
```text
Python result
    -> SQLite Outbox
    -> Kafka broker ACK
    -> Go Consumer
    -> eventId dedupe + lease/fence check
    -> MySQL task/result finalize
    -> business ACK
```
当前 P21 真正接入业务处理的是 `runtime.execution.result` v1。本地 Compose 还预建了 Tool、Model、Audit、Usage 等 Topic，作为后续事件消费者的基础；它们不等于已完成全量事件采集与计费服务。Kafka 模式由 Go 的 `KAFKA_ENABLED=true` 与 Python 的 `RUNTIME_RESULT_TRANSPORT=kafka` 配合启用；旧 HTTP Callback 仍可通过 `RUNTIME_RESULT_TRANSPORT=http` 回退。
可靠性交付的边界
当前方式是 At-Least-Once Delivery + 幂等业务处理，不宣称跨 Kafka 与 MySQL 的全局 Exactly-Once。
SQLite Outbox 必须置于可保留的数据目录；Worker 本地磁盘永久丢失且没有其他持久副本时，不能保证恢复。
本地单 Broker 没有 Kafka 集群容灾能力；生产三节点 Kafka 仅完成 Compose 配置相关验证，不能等同于真实公网部署、高可用切换或海量压测已通过。
结果长期处于 `RESULT_PENDING` 时，需要监控积压、Outbox、Consumer 和 DLQ，不能假定任何故障都能自动消失。
详见 `docs/p21/P21_EVENT_DRIVEN_RUNTIME.md` 与 `docs/p21/P21_FIX3_RELEASE_NOTES.md`。部分随源码保留的 P21 阶段文档写于最终验收之前，应以下面的验收范围说明和对应实际证据为准。
---
多租户与平台生态
资源治理以 User、Organization、Workspace、Project 为基础，覆盖 RBAC、资源归属、项目知识、Memory、模型服务、Tool / MCP、配额与审计。高风险操作需要遵守审批与治理流程；任务调度前会重新检查相关资源授权，避免排队期间被撤销的资源继续使用。
V4 平台生态提供 `/openapi/v1`、Service Account API Key、Python / TypeScript SDK、Agent Template / Version、Marketplace、Plugin Registry 与 MCP Registry。SDK 通过公开 API 调用，不直接访问内部 Runtime 或持有内部 Token。
---
技术栈
层级	技术
前端	React、TypeScript、Vite
Go 控制面	Go、Gin、MySQL、Redis、JWT
Python 运行时	Python、FastAPI、Pydantic、asyncio、LangGraph
检索与记忆	Milvus、MySQL、Redis
事件与交付	Apache Kafka、SQLite Durable Outbox、`kafka-go`、Python Kafka Producer
接入与部署	HTTP、SSE、Docker Compose、Nginx Gateway（生产配置）
集成	Tool / MCP、Public API、Python SDK、TypeScript SDK
具体依赖版本以 `backend-go/go.mod`、`runtime-python/requirements.txt`、`web-react/package.json` 和 Compose 文件为准。
项目目录
```text
AgentMesh/
├── backend-go/                 # Go API、鉴权、治理、调度、Kafka Consumer
│   ├── cmd/server/
│   ├── cmd/migrate/
│   └── internal/eventbus/
├── runtime-python/             # Agent、RAG、Memory、Tool、Worker、Outbox
│   ├── app/distributed/
│   └── tests/
├── web-react/                  # React UI、合同测试、Browser E2E
├── desktop-bridge/             # 可选的独立桌面受限执行桥
├── sdk/python/                 # Python SDK
├── sdk/typescript/             # TypeScript SDK
├── infra/                      # Gateway / MySQL 等部署资源
├── scripts/                    # Smoke、测试、发布、运维脚本
├── docs/                       # 架构、分阶段验收与运行说明
├── docker-compose.yml          # 本地基础设施（含单节点 Kafka）
├── docker-compose.production.yml
├── docker-compose.v3-ha.yml
├── VERSION
├── MANIFEST.json
└── README.md
```
---
本地运行（Windows 开发环境）
当前已验收的本地架构是：Go / Python / React 在 Windows 本机运行；Docker 只承载 MySQL、Redis、Kafka、Milvus、etcd 和 MinIO。请勿将 Docker 中间件的可用状态误当作 Go / Python 已运行。
1. 基础设施
安装 Go、Python、Node.js、Docker Desktop 和 Docker Compose。已存在的 Compose Project 固定为：
```text
agentmesh_runtime_mvp_full_v02
```
进入仓库根目录后，先检查，不要对已有共享数据直接执行 `down`、`down -v` 或全量重建：
```powershell
docker compose -p agentmesh_runtime_mvp_full_v02 ps
```
全新独立开发环境在确认没有同名共享容器与数据卷后，才可根据 `docker-compose.yml` 初始化所需服务。当前本地示例端口为 MySQL `3310`、Redis `6382`、Milvus `19530`、Kafka `29092`；容器内部 Kafka 地址为 `kafka:9092`。`kafka-init` 创建 Topic 后正常退出，不需要常驻。
2. 配置本地环境
参考 `backend-go/.env.example` 与 `runtime-python/.env.example` 设置环境变量或创建本地 `.env`（不要提交）。确保：
Go 的 `RUNTIME_INTERNAL_TOKEN` 与 Python 的 `INTERNAL_TOKEN` 一致，并配置正确的数据库、Redis 与 JWT / Governance 密钥。
Windows 本机 Go / Python 访问 Kafka 使用 `127.0.0.1:29092`；不要使用仅容器内可解析的 `kafka:9092`。
Kafka 结果链路需要 Go：`KAFKA_ENABLED=true`，Python：`RUNTIME_RESULT_TRANSPORT=kafka`。
Python 的 `KAFKA_OUTBOX_PATH` 指向可持久保存、不会被临时清理的目录。
登录后通过模型设置配置可用模型服务；离线验证可使用系统已有的 `mock` Provider，不需要把真实 API Key 写进仓库。
3. 启动 Python Runtime
在第一个 PowerShell 窗口：
```powershell
cd runtime-python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 9572
```
4. 启动 Go Control Plane
在第二个 PowerShell 窗口：
```powershell
cd backend-go
go mod download
go run ./cmd/server
```
Go Server 启动时会运行数据库迁移；独立迁移入口为 `go run ./cmd/migrate`，实际环境应按运维流程控制迁移时机。首次启动前请确认连接的是你预期的数据库。
5. 启动前端
在第三个 PowerShell 窗口：
```powershell
cd web-react
npm ci
npm run dev
```
打开 `http://localhost:5173`。Vite 默认将 `/api` 代理到 `http://127.0.0.1:8086`。可查看 Go `http://127.0.0.1:8086/health` 与 Python `http://127.0.0.1:9572/health`，并检查 Worker 心跳和 Result Transport 状态。
以上命令均应从对应子项目目录执行；如果使用虚拟环境、已有本地密钥或其他端口，以实际配置为准。
其他部署方式
仓库还提供生产 Compose、三节点 KRaft Kafka 配置、Gateway / TLS、迁移与运维脚本，详见 `docs/p10/RUNBOOK.md`。这些配置与脚本不代表当前 P21 已完成容器化生产镜像构建和公网发布验收。
---
测试与验收
常用本地测试入口：
```powershell
# Go（在 backend-go/ 中）
go test ./...
go build -mod=readonly ./cmd/server
go build -mod=readonly ./cmd/migrate

# Python（在 runtime-python/ 中）
python -m pytest -q

# Frontend（在 web-react/ 中）
npm test
npm run build

# Python SDK（在 sdk/python/ 中）
python -m unittest discover -s tests -p "test_*.py"

# TypeScript SDK（在 sdk/typescript/ 中）
npm ci
npm test
```
数据库集成测试需要独立、可清理的测试 DSN，不能把开发数据库冒充测试库；缺少 DSN 而跳过的测试不应报告为 PASS。Browser E2E、隔离测试与发布验证有专门脚本及环境要求，详见 `docs/TESTING.md`、`web-react/e2e/` 与各阶段验收文档。
已完成的 P20 / P21 验收范围
P20 Conversation History Reliability： 曾以真实栈验证 125/125 历史消息可分页恢复、刷新后历史保留、Memory Capsule 和 Redis 丢失恢复；此处的 125 是验收样本规模，不是容量上限。
P21 Windows Local Deployment — FINAL PASS： 在 Windows 本机 Go / Python / React + `agentmesh_runtime_mvp_full_v02` 中间件环境下，验证 Kafka 中断恢复、Durable Outbox、Consumer backlog 恢复、成功事件重复消费幂等、Same Worker Higher Fence、HTTP 回退与 DLQ 隐私。COMPLETING 崩溃重放故障注入记录为 21/21 PASS。
P21 构建： Windows 本地 `go build -mod=readonly ./cmd/server` 与 `./cmd/migrate` 已通过，未修改 `go.mod` / `go.sum`。
尚未宣称通过： P21 的 Docker 镜像生产构建、公网多节点部署、真实生产流量高并发压测，以及预建 Topic 上的完整 Tool / Model / Audit / Usage 事件消费者。
测试报告反映特定版本、配置与场景的证据，不应解读为对所有网络故障或数据丢失场景的无限保证。
---
安全与数据边界
AgentMesh 在源码中实现了身份认证、RBAC / Project Scope、BYOK 凭据保护、Tool / MCP Governance、Desktop 高风险审批与部分 Trace / DLQ 脱敏机制。实际对外部署仍需独立核实密钥、TLS、网络隔离、持久化备份与运维权限。
以下内容不得进入 Git 或 Release 源码包：
```text
.env / .env.local / .env.production
API Key / JWT Secret / 内部 Token / TLS 私钥
runtime-python/data/ 及 SQLite Outbox
node_modules/ / .venv/ / __pycache__/ / .pytest_cache/
dist/ / 日志 / 备份 / 用户上传 / 本地数据库
```
`MANIFEST.json` 是对应源码快照的完整性清单；修改 `main` 之后不能假设旧 Manifest 自动覆盖新提交。正式打包与发布需重新执行相应校验，不能直接复用旧 Release 的哈希。
文档入口
文档	用途
`docs/ARCHITECTURE.md`	初期 Control Plane / Runtime 职责边界
`docs/v2/ARCHITECTURE.md`	多模态检索与 Evaluation
`docs/v3/ARCHITECTURE.md`	Multi-node、Lease / Fencing、Dispatcher HA
`docs/v4/ARCHITECTURE.md`	模型服务池、Public API 与生态治理
`docs/p21/P21_EVENT_DRIVEN_RUNTIME.md`	Kafka / Outbox / Consumer 设计
`docs/p10/RUNBOOK.md`	Compose、Gateway、迁移与生产运维
`docs/p12/SECURITY_BOUNDARIES.md`	Release 与安全边界
`desktop-bridge/README.md`	桌面能力、权限及启动
`sdk/README.md`	Python / TypeScript SDK
项目演进与后续方向
从 Agent / Memory / Tool / MCP 基础能力出发，项目逐步加入分布式执行、多租户治理、多模态与评测、平台生态、长会话可靠性和 Kafka 结果事件平面。后续仍需根据实际部署需求评估：生产 Kafka / Outbox 运维、高并发容量、更加完整的事件消费者、监控告警与对外发布流程。
项目关注的核心工程问题： 当多个用户和 Agent 同时工作、模型和工具可能失败、网络与 Worker 可能中断时，怎样明确任务所有权、隔离数据、保留执行证据，并在不重复业务副作用的前提下安全恢复。
---
License
Apache License 2.0，详见 `LICENSE`。
Author
Qin LingHang · GitHub
如果这个项目对你的 Agent / Multi-Agent 开发有所帮助，欢迎 Star ⭐
