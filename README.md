AgentMesh
面向多用户、多项目、多模型场景的开源 Agent 应用平台。
基于 Go + Python + React + TypeScript 构建，覆盖 Agent Runtime、Multi-Agent、RAG、Memory、Tool、MCP、BYOK、RBAC、分布式执行、Desktop Bridge、可观测性与生产部署。

Release License Go Python React

当前稳定版本： v1.0.0
开源协议： Apache License 2.0
项目状态： v1.0.0 正式版本已完成自动化验收与 Release Strict-tree 校验。

项目简介
AgentMesh 是一个面向真实工程场景设计的 Agent 应用平台。

它并不是简单地：

Prompt
  ↓
LLM
  ↓
Answer
而是围绕真实 Agent 系统逐步构建：

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
RAG / Memory / Tool / MCP / Desktop
   ↓
DAG / Multi-Agent Execution
   ↓
Evaluation / Observability
   ↓
最终回答
当系统开始面对：

多用户
多项目
多组织
多模型
多 Agent
多 Tool
多 MCP Server
知识库
长期 Memory
BYOK
权限治理
分布式 Worker
任务恢复
可观测性
生产部署
问题就不再只是：

“如何调用一次大模型？”

而会演变成：

“一个真正可扩展、可治理、可观测、可恢复的 Agent 平台应该如何设计？”

AgentMesh 就是围绕这些问题进行的一套完整工程实践。

架构设计
AgentMesh 采用：

Go Control Plane
        +
Python Agent Runtime
        +
React / TypeScript Frontend
        +
Desktop Bridge
的分层架构。

Go Control Plane
负责：

Authentication
User / Session
Conversation
Organization
Project
RBAC
Governance
BYOK
Model Configuration
Tool / MCP Registry
Task Control
Public API
Service Account
Runtime 调用
多租户资源边界
Go 主要回答：

谁可以执行？
执行什么？
资源属于谁？
是否允许执行？
Python Agent Runtime
负责：

Agent Runtime
LangGraph Workflow
Multi-Agent
DAG Execution
Capability Discovery
RAG
Knowledge
Memory
Tool Runtime
MCP
Desktop Tool
Model Gateway
Adaptive Routing
Evaluation
Distributed Execution
Runtime Observability
Python 主要回答：

这个任务应该怎么执行？
React + TypeScript
负责用户交互与平台管理：

Workspace
Session
Agent
Knowledge Center
Memory
Model Settings
Governance
Tasks
Run Details
Platform Ecosystem
Profile
Desktop 能力入口
Desktop Bridge
提供受治理的本地桌面能力：

Filesystem
Process Discovery
Executable Discovery
Windows UI Automation
Computer Use
Audit
Local Desktop Tool Runtime
Desktop Bridge 不被视为无限制本地执行环境，所有能力仍需经过策略与权限边界。

核心能力
1. Agent Runtime
AgentMesh 将 AI 执行能力从业务控制面中独立出来。

当前 Runtime 包括：

Agent Capability Profile
Agent Resolver
Agent Workflow
LangGraph Workflow
DAG Execution
Collaboration Planner
A2A Discovery
A2A Execution
Runtime Context
Task Resume
Execution Trace
Adaptive Routing
Evaluation
Distributed Runtime
典型执行流程：

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
既支持单 Agent，也支持：

串行 Agent
并行 Agent
多步骤 DAG
Agent 协作
能力发现
可恢复任务执行
2. Multi-Agent
对于复杂任务，Runtime 可以根据任务能力需求选择不同 Agent，并形成执行计划。

User Request
      ↓
Capability Analysis
      ↓
Agent Discovery
      ↓
Collaboration Planner
      ↓
DAG
      ↓
Multiple Agents
      ↓
Reducer / Aggregation
      ↓
Final Answer
AgentMesh 更关注 Agent 之间的：

能力选择
协作关系
执行顺序
状态传递
失败恢复
最终结果聚合
而不是简单地把多个模型调用串联起来。

RAG 与 Knowledge
3. Knowledge Base
AgentMesh 提供用户级与项目级 Knowledge 能力。

当前包括：

Knowledge Base
Document Parsing
Document Ingestion
Chunking
Embedding
Milvus Vector Search
Hybrid Retrieval
Query Intelligence
Adaptive RAG Routing
Reranker
Evidence Provenance
Citation Projection
Citation Validation
Grounded Answer Guard
同时支持多模态知识能力：

PDF / Image Knowledge
Multi-modal Retrieval
Visual Evidence
TEXT Retrieval
VISUAL Retrieval
HYBRID Retrieval
Vision Provider
VLM Routing
RAG 不会对每一次请求无条件执行。

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
这样可以减少：

无意义检索
Context 浪费
无关知识干扰
不必要延迟
Conversation 与 Memory
4. Durable Conversation History
AgentMesh 将聊天记录作为持久化业务数据处理，而不是只依赖 Runtime 内存。

当前支持：

Durable Conversation History
Conversation Pagination
Older Message Loading
Long Conversation Recovery
Scroll Anchor Preservation
Same-conversation Refresh
Session Restore
MySQL Durable History
Redis Working Context
Memory Capsule
Redis-loss Recovery
长会话场景中，可以逐步加载历史消息，同时保持用户当前阅读位置。

MySQL
  ↓
Durable Conversation History
  ↓
分页加载
  ↓
Workspace
即使 Runtime Redis 临时工作状态丢失，持久化 Conversation History 仍然可以从 MySQL 恢复。

5. Memory
AgentMesh 将：

Conversation History
与：

Long-term Memory
进行区分。

短期 Memory
用于当前 Session / Runtime：

Conversation Context
Recent Messages
Redis Working Memory
Context Budget
Session State
长期 Memory
用于真正需要跨会话复用的信息：

Automatic Memory Write
Long-term Memory
Memory Retrieval
Memory Injection
Memory Forget
Memory Management
Memory Observability
系统不会简单地把所有聊天内容永久保存为长期记忆。

对于以下敏感数据：

Password
Token
API Key
Private Key
Secret
会进行限制与隔离。

Tool Runtime
6. Tool Execution
AgentMesh 支持 Agent 调用真实工具完成任务。

目前包括：

Internal Tool
HTTP Tool
Built-in Tool
Tool Registry
Tool Loop
Tool Governance
Secure Action
Approval
Calculator
Desktop Tool
执行链路：

Agent
 ↓
Tool Selection
 ↓
Tool Registry
 ↓
Governance
 ↓
Approval
 ↓
Tool Execution
 ↓
Observation
 ↓
Agent
对于存在副作用的操作，可以通过 Governance 与 Approval 控制 Agent 的行为边界。

MCP
7. Model Context Protocol
AgentMesh 支持 MCP（Model Context Protocol）。

目前包括：

MCP Client
MCP Manager
MCP Contract
MCP Mapping
MCP Retry / Backoff
MCP Tool Integration
MCP Registry
Agent Runtime
      ↓
MCP Manager
      ↓
MCP Client
      ↓
External MCP Server
      ↓
Tools / Resources
AgentMesh 将：

Explicit Tool Execution
与：

MCP Discovery
区分处理。

即使当前任务不需要 MCP Discovery，用户显式配置的 Internal / HTTP Tool 仍然可以独立执行。

Desktop Bridge
8. Local Desktop Agent
AgentMesh 提供 Desktop Bridge，使 Agent 可以在受控边界内连接用户本机环境。

当前能力包括：

Filesystem Access
Read-only Boundary
Process Discovery
Executable Discovery
Windows UI Automation
Computer Use
Desktop Tool Runtime
Audit
Embedded Runtime Support
基本结构：

Agent Runtime
      ↓
Desktop Tool
      ↓
Desktop Bridge
      ↓
Policy
      ↓
Local Files / Process / UI
Desktop Bridge 不直接赋予 Agent 任意系统权限。

本地能力仍然受到：

Path Policy
Read-only Policy
Process Policy
Governance
Audit
等规则约束。

Model Gateway
9. Multi-model / BYOK
AgentMesh 将模型访问统一封装在 Model Gateway 中。

目前包括：

Model Provider
Model Gateway
Model Runtime
Model Routing
Adaptive Model Routing
Project Model Configuration
User Model Configuration
BYOK
BYOK：

Bring Your Own Key
允许不同用户使用自己的模型凭据。

User
 ↓
Provider
 ↓
API Key
 ↓
Model
 ↓
Project Policy
 ↓
Agent Runtime
敏感模型凭据不会作为普通业务字段直接暴露给前端。

Governance
10. Organization / Project
核心资源关系：

User
 │
 ├── Personal Project
 │
 └── Organization
        │
        ├── Members
        │
        └── Projects
当前治理能力包括：

Organization
Organization Member
Project
Organization / Project Binding
RBAC
Project Governance
Tool Governance
MCP Governance
BYOK Governance
Quota / Usage
Audit / Redaction
Runtime Governance Recheck
AgentMesh 不再只面向单用户 Demo，而是支持：

User
Organization
Project
三个层面的资源模型。

Multi-tenant Isolation
11. Tenant Isolation
多租户隔离是 AgentMesh 的核心设计边界之一。

隔离范围包括：

User
Organization
Project
Conversation
Session
Knowledge Base
Memory
Model Configuration
Tool
MCP
Runtime Resource
后端不会仅信任前端传入的资源 ID。

资源访问会结合：

User Scope
+
Organization Scope
+
Project Scope
进行实际归属判断。

Distributed Runtime
12. Multi-node / HA
AgentMesh 已实现分布式 Runtime 基础能力。

当前包括：

Durable Queue
Worker Registration
Worker Heartbeat
Runtime Node Registration
Runtime Node Discovery
Capacity-aware Scheduling
Lease
Cross-node Fencing
Dispatcher HA Lease
Dispatcher Epoch
Idempotent Execution
Backpressure
Deadline
Cancellation
Safe Retry Boundary
Worker Recovery
Node Recovery
Safe Task Reassignment
Circuit Breaker
Graceful Drain
Graceful Shutdown
Distributed Runtime Metrics
Runtime Topology
整体结构：

Control Plane
      ↓
Durable Queue
      ↓
Dispatcher
      ↓
Worker Pool
      ↓
Agent Runtime
任务执行不再依赖单个进程的临时内存状态。

Platform Ecosystem
13. Public API / SDK / Marketplace
AgentMesh v1.0.0 已包含平台生态能力。

Public API
/openapi/v1
Project-scoped Service Account
API Key
Scope
Revocation
Expiration
Usage
Idempotency-Key
Project Boundary
Official SDK
目前包含：

sdk/python/
sdk/typescript/
即：

Python SDK
TypeScript SDK
Marketplace
支持：

Agent Package
MCP Package
Plugin Registry
Package Versioning
Publish
Import
Export
Install
Enable
Disable
Uninstall
Permission Governance
Manifest Validation
Endpoint Validation
典型调用链：

External App / CI
      ↓
Service Account API Key
      ↓
/openapi/v1
      ↓
Scope + Project Boundary
      ↓
Idempotency
      ↓
AgentMesh Runtime
Marketplace 安装不会绕过现有：

Project Boundary
RBAC
Tool Governance
MCP Governance
BYOK Governance
Evaluation
14. Agent Evaluation
AgentMesh 内置 Evaluation 能力。

当前包括：

Eval Dataset
Baseline
Scorecard
Runtime Evaluation
Routing Evaluation
Execution Metrics
LLM-as-a-Judge
Eval Case 位于：

runtime-python/evals/
用于检测 Runtime 策略变化是否造成行为回归。

Observability
15. Run Details
AgentMesh 将：

最终回答
和：

执行过程
进行分离。

Workspace 保持正常任务交互，而执行细节进入独立 Run Details。

目前包括：

Overview
Execution Timeline
Agent DAG
Tool Trace
MCP Trace
RAG Trace
Memory Trace
Routing Trace
Reliability Trace
Desktop Trace
Capability Discovery
Eval Scorecard
Run Health
Feedback
这样既保持正常使用界面的简洁，也方便开发者查看 Agent 内部执行过程。

总体架构
┌──────────────────────────────────────────────────────────────┐
│                    React + TypeScript                        │
│                          Frontend                            │
│                                                              │
│ Workspace / Agent / Knowledge / Memory / Governance          │
│ Model Settings / Tasks / Run Details / Ecosystem             │
└─────────────────────────────┬────────────────────────────────┘
                              │
                          HTTP / SSE
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                     Go Control Plane                         │
│                                                              │
│ Auth / User / Session / Conversation                         │
│ Organization / Project / RBAC                                │
│ Governance / Tool / MCP                                      │
│ Model Configuration                                          │
│ Public API / Service Account / Marketplace                   │
│ Task Control / Tenant Isolation                              │
└─────────────────────────────┬────────────────────────────────┘
                              │
                       Runtime Request
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    Python Agent Runtime                      │
│                                                              │
│ Agent / LangGraph / DAG / Multi-Agent                        │
│ RAG / Knowledge / Memory                                     │
│ Tool / MCP / Desktop                                         │
│ Model Gateway / Adaptive Routing                             │
│ Evaluation / Observability                                   │
│ Distributed Runtime                                          │
└───────────────┬────────────────┬────────────────┬─────────────┘
                │                │                │
                ▼                ▼                ▼
              MySQL            Redis            Milvus
                                                   │
                                                   ▼
                                           Desktop Bridge
技术栈
模块	技术
Control Plane	Go
Agent Runtime	Python
Runtime API	FastAPI
Agent Workflow	LangGraph
Frontend	React + TypeScript
Frontend Build	Vite
Relational Database	MySQL
Cache / Working Memory	Redis
Vector Database	Milvus
Desktop Bridge	Python
Container	Docker
Orchestration	Docker Compose
Gateway	Nginx
Communication	HTTP / SSE
Tool Protocol	MCP
Python Testing	Pytest
Go Testing	Go Test
Frontend Testing	Node Contract Test / Browser E2E
项目目录
AgentMesh/
│
├── backend-go/
│   ├── cmd/
│   ├── internal/
│   │   ├── config/
│   │   ├── db/
│   │   ├── handler/
│   │   ├── middleware/
│   │   ├── model/
│   │   ├── repository/
│   │   ├── router/
│   │   ├── runtime/
│   │   ├── security/
│   │   └── service/
│   └── Dockerfile
│
├── runtime-python/
│   ├── app/
│   │   ├── agents/
│   │   ├── capabilities/
│   │   ├── distributed/
│   │   ├── eval/
│   │   ├── knowledge/
│   │   ├── mcp/
│   │   ├── memory/
│   │   ├── models/
│   │   ├── multimodal/
│   │   ├── rag/
│   │   ├── services/
│   │   └── tools/
│   ├── evals/
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
├── desktop-bridge/
│   ├── desktop_bridge/
│   ├── tests/
│   └── README.md
│
├── sdk/
│   ├── python/
│   └── typescript/
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
├── MANIFEST.json
├── VERSION
├── LICENSE
└── README.md
快速开始
环境要求
建议安装：

Go
Python 3
Node.js
npm
Docker
Docker Compose
主要基础设施：

MySQL
Redis
Milvus
具体依赖版本以项目配置文件和 Docker 配置为准。

Python Runtime
cd runtime-python

python -m venv .venv
Windows PowerShell：

.\.venv\Scripts\Activate.ps1
Linux / macOS：

source .venv/bin/activate
安装依赖：

pip install -r requirements.txt
启动 Runtime：

uvicorn app.main:app --reload
Go Backend
cd backend-go

go mod download

go run ./cmd/server
测试：

go test ./...
React Frontend
cd web-react

npm install

npm run dev
测试：

npm test
生产构建：

npm run build
Docker
项目根目录提供：

docker-compose.yml
docker-compose.production.yml
开发环境可根据实际配置启动：

docker compose up -d
生产部署请根据：

.env.production.example
创建真实生产配置。

不要将以下敏感信息提交到 Git：

.env
.env.production
API Key
JWT Secret
SMTP Password
TLS Private Key
Provider Secret
Environment
仓库提供 example 配置文件，例如：

.env.auth-session.example
.env.production.example
backend-go/.env.example
runtime-python/.env.example
runtime-python/.env.desktop.example
desktop-bridge/.env.example
推荐：

Example Config
      ↓
Copy
      ↓
Local / Production Config
      ↓
Secret Management
真实 Secret 不应写回 example 文件。

测试体系
Python
cd runtime-python
pytest -q
Go
cd backend-go
go test ./...
Frontend
cd web-react
npm test
npm run build
项目同时包含：

Browser E2E
Session Restore E2E
Organization Governance E2E
Tenant Isolation Tests
Distributed Runtime Tests
V4 Platform Ecosystem Tests
V4.1 Conversation Isolation Tests
Desktop Bridge Tests
P20 Conversation History Reliability Tests
Runtime Contract Tests
Release Validation
v1.0.0 正式发布前已完成自动化验收以及 Release Strict-tree 校验。

Security
AgentMesh 重点关注以下安全边界。

Authentication
JWT Authentication
Session Restore
Authentication Middleware
Authorization
RBAC
User Scope
Organization Scope
Project Scope
IDOR Defense
Secret
BYOK Secret Protection
Environment Secret Isolation
Memory Secret Rejection
Sensitive Configuration Exclusion
Agent Action
Tool Governance
MCP Governance
Secure Action
Approval
Desktop Policy Boundary
Data
Tenant Isolation
Runtime Data Isolation
Knowledge Scope
Memory Scope
Conversation Isolation
Release
Forbidden File Scan
Runtime Data Scan
Secret / Privacy Scan
Manifest Validation
Archive Validation
Strict-tree Validation
Release
当前稳定版本：

AgentMesh v1.0.0
正式版本演进：

P1 - P12
    ↓
Production-ready Baseline
    ↓
V2 Intelligence & Multimodal
    ↓
V3 Distributed Runtime / Multi-node / HA
    ↓
V4 Platform Ecosystem
    ↓
V4.1 Runtime / Knowledge / Desktop / Continuity
    ↓
P20 Conversation History Reliability
    ↓
Full Automated Acceptance
    ↓
Release Manifest
    ↓
Strict-tree Validation
    ↓
AgentMesh v1.0.0
v1.0.0-rc.1、v1.0.0-rc.2 保留为历史 Release Candidate。

Source Integrity
正式源码包含：

MANIFEST.json
用于记录源码文件的：

Relative Path
File Size
SHA-256
正式 Manifest：

version:      1.0.0
artifactType: release-source
status:       release
publishable:  true
MANIFEST.json 本身不参与自身 Hash 计算。

正式源码包由 Git Tag 构建，而不是直接压缩本地开发工作区。

Repository Hygiene
以下内容不应进入 Git 或正式 Source Release：

.env
.env.production
.env.local
node_modules
.venv
__pycache__
.pytest_cache
dist
logs
tmp
runtime data
Local Database
Runtime Uploads
User Attachments
TLS Private Key
临时测试目录
临时验收产物
这样可以避免：

Secret 泄漏
本地路径泄漏
运行数据泄漏
无关依赖进入源码包
本地缓存污染 Release
Documentation
项目文档位于：

docs/
推荐阅读：

总体架构
测试说明
生产运行手册
P11 Completion
最终发布说明
完整人工验收
V4 Architecture
V4 Public API
V4 Marketplace
V4 Security
OpenAPI
Roadmap
v1.0.0 已冻结当前功能范围。

后续如果重新启动新版本开发，将优先考虑：

Kubernetes
Helm
Terraform
Cloud Multi-node Deployment
Enterprise SSO / SCIM
Billing Provider Integration
完整 Observability Vendor Integration
更大规模 Capacity / Load Validation
Mobile Client
更完整的插件生态
这些能力不属于当前 v1.0.0 发布范围。

为什么做 AgentMesh
很多 Agent Demo 可以很快完成：

Prompt
 ↓
LLM
 ↓
Tool
 ↓
Answer
但真实系统最终一定会遇到：

Runtime 如何设计？
资源如何隔离？
Agent 如何路由？
Tool 如何治理？
MCP 如何接入？
Memory 如何控制？
历史会话如何恢复？
任务如何重试？
模型如何切换？
多节点如何调度？
Worker 故障如何恢复？
执行过程如何观测？
系统如何上线？
AgentMesh 的目标不是只完成一个“能聊天”的 AI 页面。

而是：

从后端工程、AI Runtime、Agent 编排、RAG、Memory、Tool、MCP、多租户治理、分布式执行、Desktop Agent 到生产发布，完整实现一次真实 Agent 平台工程。

项目定位
AgentMesh 更偏向：

Agent Infrastructure
        +
Agent Application Platform
        +
AI Backend Engineering
而不是一个单纯的聊天 Demo。

项目重点关注：

Agent Runtime
AI Application Architecture
Backend Engineering
Multi-Agent
RAG
Memory
Tool
MCP
Model Gateway
BYOK
Governance
Multi-tenant Isolation
Distributed Runtime
Desktop Agent
Evaluation
Observability
Production Readiness
Contribution
欢迎通过以下方式参与：

Issue
Pull Request
Architecture Discussion
Bug Report
Feature Proposal
提交代码前，建议至少完成对应模块测试。

License
AgentMesh 基于 Apache License 2.0 开源。

详情请参阅：

LICENSE

Disclaimer
AgentMesh v1.0.0 已进入正式发布阶段。

实际部署到不同生产环境时，仍建议根据具体业务要求进一步配置：

Secret Management
HTTPS / TLS
数据备份与恢复
日志与审计
Monitoring
Alert
Runtime Resource Limit
High Availability
Disaster Recovery
Provider Quota Control
Cost Control
生产环境必须使用独立配置与 Secret，不应复用开发环境中的本地运行数据。

AgentMesh
Build Agents.
Connect Tools.
Govern Runtime.
面向真实工程场景构建可扩展、可治理、可观测、可恢复的 Agent Runtime 与应用平台。
