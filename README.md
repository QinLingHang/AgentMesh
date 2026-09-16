<div align="center">
AgentMesh
多用户 · 多项目 · 分布式 Agent 应用与运行平台
Go Control Plane · Python Agent Runtime · React / TypeScript · Kafka Event Plane
![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)
![Go](https://img.shields.io/badge/Control%20Plane-Go-00ADD8)
![Python](https://img.shields.io/badge/Agent%20Runtime-Python-3776AB)
![React](https://img.shields.io/badge/Web-React%20%2B%20TypeScript-149ECA)
![Kafka](https://img.shields.io/badge/Event%20Plane-Kafka-231F20)
从 Agent 编排、知识与记忆，到分布式执行、结果可靠交付与多租户治理。
核心能力 · 系统架构 · 快速开始 · 验证情况 · 技术文档
</div>
---
📖 项目简介
AgentMesh 是一个面向多用户、多项目场景的 Agent 应用与运行时平台。项目采用 Go 控制面、Python Agent 运行时与 React / TypeScript 前端的分层架构，围绕任务编排、RAG、Memory、Tool / MCP、权限治理、分布式执行与运行可观测性开展工程实践。
区别于简单的聊天接口封装，AgentMesh 关注的是：Agent 在真实任务中遇到网络中断、Worker 失联、消息重复、长期会话和多用户资源隔离时，系统如何安全地执行、恢复并保留结果。
> **版本说明**：仓库已发布的 Release / Tag 是 `v1.0.0`；后续 V2 / V3 / V4 / V4.1、P20、P21 属于主线持续开发成果。P21 已通过 **Windows 本地部署验收**，但尚未完成包含 P21 的新版 Release、Docker 镜像生产构建、真实生产集群部署或海量并发压测。请勿将这些验收范围混为一谈。
✨ 核心能力
01 · Agent 编排与智能运行
Multi-Agent：Task Profile、Capability Discovery、Agent Resolver、Agent Routing、串行 / 并行 / DAG 协作、运行时重新调度。
多模态 RAG：文本与图片知识摄取、Embedding、Milvus、Hybrid Retrieval、Rerank、Citation；支持 `TEXT` / `VISUAL` / `HYBRID` 模式。
Conversation & Memory：MySQL 持久化历史、历史分页、Redis Working Memory、Context Budget、Memory Capsule、会话恢复。
Tool / MCP：工具注册与发现、Schema 校验、调用执行、结果回填、治理检查与高风险操作审批。
Model Gateway & BYOK：Provider 抽象、个人模型服务池、任务级模型选择、项目配置回退、密钥隔离、超时与安全重试。
02 · 分布式执行与可靠交付
Durable Runtime：MySQL 持久队列、Worker / Node 心跳、容量感知调度、Lease、Fencing、Dispatcher HA、Deadline / Cancel 与安全恢复。
Kafka Event Plane：Python SQLite Durable Outbox、Runtime Result 事件、Go Consumer、事件幂等账本、DLQ 和消费进度管理。
双重确认：区分 Kafka Broker ACK 与 Go Business ACK；通过 `RESULT_PENDING` 避免结果交付期间误判 Worker 丢失。
HTTP 兼容：现有 HTTP Callback 仍可作为结果传输的兼容模式。
03 · 平台治理与生态
多租户治理：User / Organization / Workspace / Project、RBAC、资源归属、知识与记忆隔离、配额和审计。
平台能力：Public API、API Key / Service Account、Python / TypeScript SDK、Agent Template / Version、Marketplace、Plugin / MCP Registry。
桌面能力：受控本地文件、注册应用和 CLI 工具；可选 Windows Computer Use 与独立 Desktop Bridge。
可观测性：Run Details、DAG / Trace、路由、Tool / MCP、错误与恢复事件、部分用量和评测指标。
> **能力边界**：Multi-Agent 指任务规划与编排，不等于模型可无约束地相互调用；Desktop 能力也不意味着浏览器可以直接取得任意本机执行权限。User-global Memory 与 Project Knowledge 分别按用户和项目隔离。
---
🏗 系统架构
组件与职责
组件	核心职责
React / TypeScript	Workspace、Chat、知识管理、治理与 Run Details
Go Control Plane	认证、资源与权限、任务状态、持久队列、调度、Kafka 结果消费
Python Agent Runtime	Agent / DAG、LLM、RAG、Memory、Tool / MCP、Worker 与结果发布
MySQL / Redis / Milvus	权威业务数据 / 工作记忆与缓存 / 向量检索
SQLite Outbox + Kafka	执行结果先持久化，再异步交付 Go
任务调度（Command Plane）
```text
React / SDK
    │ HTTP / SSE
    ▼
Go Control Plane ───────► MySQL Durable Queue
                               │
                               ▼
                         Go Dispatcher
                               │ HTTP Dispatch
                               ▼
                         Python Worker
                               │
                  Agent / LLM / RAG / Tool / MCP
```
结果交付（Event Plane · P21）
```text
Python Worker 完成计算
          │
          ▼
   SQLite Durable Outbox
          │
          ▼
       Kafka Topic ───────────► Go Result Consumer
       Broker ACK                     │
          │                 幂等检查 / Lease / Fencing
          │                           │
          │                           ▼
          │                     MySQL Finalize
          │                           │
          └────── 等待 Business ACK ◄─┘
                         │
                         ▼
                  释放执行归属
```
两条链路不能混为一谈：Go 的 MySQL Durable Queue 负责“任务如何被调度”，Kafka 负责“执行结果如何异步交付”；Kafka 不替代浏览器 HTTP / SSE，也不替代任务调度器。
P21 可靠性机制
机制	解决的问题
SQLite Outbox	Kafka 暂时不可用时，保留已生成但尚未投递的结果
Broker / Business ACK	防止 Kafka 已接收、Go 尚未完成时提前释放执行归属
`RESULT_PENDING`	防止结果等待消费期间被错误回收
`event_id` + 幂等账本	防止至少一次投递造成重复业务副作用
Lease / Fencing	防止旧 Worker 的结果覆盖新执行归属
DLQ / Offset 处理	隔离异常事件，避免错误跳过尚未处理的消息
当前接入范围：P21 实际打通的是 Runtime Result 事件。Tool、Model、Audit、Usage 等 Topic 已作为扩展基础预建，并不代表相应事件消费者或完整计费系统已经上线。当前使用的是 At-Least-Once Delivery + 幂等业务处理，不宣称 Kafka 与 MySQL 之间具有全局 Exactly-Once。
查看 P21 设计与实现说明 →
---
🛠 技术栈
层级	技术
前端	React、TypeScript、Vite
控制面	Go、Gin、JWT
Agent Runtime	Python、FastAPI、Pydantic、asyncio、LangGraph
数据与检索	MySQL、Redis、Milvus
事件传输	Apache Kafka、SQLite Durable Outbox、`kafka-go`、Python Kafka Producer
接入与运维	HTTP / SSE、Docker Compose、Nginx Gateway（生产配置）
具体版本以 `backend-go/go.mod`、`runtime-python/requirements.txt`、`web-react/package.json` 和 Compose 文件为准。
<details>
<summary><b>📁 查看项目目录</b></summary>
```text
AgentMesh/
├── backend-go/                 # Go Control Plane、调度、Kafka Consumer
├── runtime-python/             # Agent Runtime、Worker、SQLite Outbox
├── web-react/                  # React / TypeScript Web
├── desktop-bridge/             # 可选桌面执行桥
├── sdk/                        # Python / TypeScript SDK
├── infra/                      # Gateway 与基础设施资源
├── scripts/                    # 测试、发布与运维脚本
├── docs/                       # 架构与阶段验收文档
├── docker-compose.yml          # 本地基础设施（单节点 Kafka）
├── docker-compose.production.yml
├── docker-compose.v3-ha.yml
├── VERSION
├── MANIFEST.json
└── README.md
```
</details>
---
🚀 快速开始
以下流程面向已验收的 Windows 本地开发架构：Go、Python 和 React 在 Windows 本机运行；Docker 只承载 MySQL、Redis、Kafka、Milvus、etcd、MinIO。
1 · 获取代码并检查基础设施
```powershell
git clone https://github.com/QinLingHang/AgentMesh.git
cd AgentMesh

docker compose -p agentmesh_runtime_mvp_full_v02 ps
```
当前开发环境的 Compose Project 名称为 `agentmesh_runtime_mvp_full_v02`。已有共享容器或数据时，不要直接执行 `down`、`down -v` 或全量重建。 首次独立部署需先确认容器名、数据卷和端口没有冲突，再按 Compose 配置初始化依赖。
本机服务	示例地址
MySQL	`127.0.0.1:3310`
Redis	`127.0.0.1:6382`
Milvus	`127.0.0.1:19530`
Kafka	`127.0.0.1:29092`
容器间访问 Kafka 使用 `kafka:9092`；Windows 本机 Go / Python 使用 `127.0.0.1:29092`。`kafka-init` 创建 Topic 后正常退出，无需常驻。
2 · 配置环境变量
参考 `backend-go/.env.example`、`runtime-python/.env.example`，设置本地环境变量或创建不提交到 Git 的 `.env` 文件。
```dotenv
# Go Control Plane
KAFKA_ENABLED=true
KAFKA_BROKERS=127.0.0.1:29092

# Python Runtime
RUNTIME_RESULT_TRANSPORT=kafka
KAFKA_BROKERS=127.0.0.1:29092
KAFKA_OUTBOX_PATH=./data/runtime_result_outbox.sqlite3
```
还需根据实际环境配置数据库、Redis、JWT、Governance Key，以及一致的 Go `RUNTIME_INTERNAL_TOKEN` / Python `INTERNAL_TOKEN`。Outbox 必须放在可保留的目录，不能作为临时缓存随意清理。登录后通过模型设置启用可用模型服务；离线验收可使用已有 `mock` Provider。
3 · 启动后端和前端
分别打开三个 PowerShell 窗口；以下命令均在仓库根目录开始执行。
窗口 A — Python Runtime
```powershell
cd runtime-python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 9572
```
窗口 B — Go Control Plane
```powershell
cd backend-go
go mod download
go run ./cmd/server
```
窗口 C — React Web
```powershell
cd web-react
npm ci
npm run dev
```
浏览器打开 http://localhost:5173。Vite 默认将 `/api` 代理到 Go 的 `http://127.0.0.1:8086`。运行后可检查：
Go Health：`http://127.0.0.1:8086/health`
Python Health：`http://127.0.0.1:9572/health`
Worker 心跳、Kafka Result Transport、Outbox 待投递数量
> Go Server 启动时会运行数据库迁移；独立迁移入口是 `go run ./cmd/migrate`。首次启动前请先确认连接的是预期数据库。生产 Compose、三节点 Kafka、Gateway / TLS 等配置不属于本次 Windows 本地验收范围，详见 [P10 Runbook](docs/p10/RUNBOOK.md)。
---
✅ 验证情况
范围	已取得的验收结果
P20 · Conversation History	125/125 历史消息恢复、刷新保留、Memory Capsule、Redis 丢失恢复通过
P21 · Kafka / Outbox	Kafka 中断恢复、Go 积压恢复、重复成功事件幂等、DLQ 隐私与 Offset-skip 通过
P21 · Worker / Fencing	Same Worker Higher Fence 真实栈通过；最终任务来自更高 Fence
P21 · Crash Replay	COMPLETING 崩溃重放故障注入 21/21 PASS
P21 · Windows Go Build	`server` 与 `migrate` 均通过 `-mod=readonly` 构建
验收结论：P21 Windows Local Deployment — FINAL PASS。 这意味着上述本地配置与测试覆盖的关键场景通过，并非对所有故障模式作无条件保证。P20 的 `125/125` 是测试样本规模，不是系统容量上限。
尚未完成的发布与容量验收：包含 P21 的新版 Release、Docker 镜像生产构建、公网多节点部署、Kafka 集群高可用切换、海量并发压测和预建 Topic 对应的完整下游消费者。开发环境的单 Broker Kafka 也不具备集群级容灾能力。
<details>
<summary><b>🧪 常用测试命令</b></summary>
```powershell
# backend-go/
go test ./...
go build -mod=readonly ./cmd/server
go build -mod=readonly ./cmd/migrate

# runtime-python/
python -m pytest -q

# web-react/
npm test
npm run build
```
数据库集成测试应使用独立测试 DSN；缺少 DSN 而跳过的测试不能计为 PASS。SDK、Browser E2E 和发布验收请参考 测试说明 及相关阶段文档。
</details>
---
🔐 安全与数据边界
平台实现认证、RBAC / Project Scope、BYOK 凭据保护、Tool / MCP 治理及部分 Trace / DLQ 脱敏。对外部署仍需独立核实密钥管理、TLS、网络隔离、存储备份和运维权限。
不要提交 `.env`、API Key、JWT Secret、内部 Token、TLS 私钥、`runtime-python/data/`、SQLite Outbox、用户文件、日志、数据库、`node_modules/`、`.venv/` 或测试缓存。
`MANIFEST.json` 属于对应源码快照的完整性清单；主线代码变更后，正式发布需重新生成并校验，不能复用旧 Release 哈希。
---
📚 技术文档
文档	内容
整体架构	Go Control Plane / Python Runtime 分层
V2 架构	多模态检索与 Evaluation
V3 架构	多节点、Lease / Fencing、Dispatcher HA
V4 架构	模型服务池、Public API 与平台生态
P21 事件平面	Kafka、Outbox、Consumer 与业务确认
P21 FIX3 说明	RESULT_PENDING、Fencing 与可靠性修复
P10 运行手册	Compose、Gateway、数据库迁移与运维
安全边界	发布与安全注意事项
Desktop Bridge · SDK	桌面能力与 SDK 接入
---
🗺 后续方向
持续完善生产 Kafka / Outbox 运维、负载与容量测试、完整事件消费者、监控告警及版本发布流程。AgentMesh 的重点是让 Agent 在多用户、长任务、网络不可靠与 Worker 可能故障的环境下，具有明确的执行归属、可观测的过程和可恢复的业务结果。
---
<div align="center">
Apache License 2.0 · LICENSE
Made by Qin LingHang
如果 AgentMesh 对你的 Agent / Multi-Agent 学习有所帮助，欢迎 Star ⭐
</div>
