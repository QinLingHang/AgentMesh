# AgentMesh

> A production-oriented multi-agent execution platform built with Go, Python and React.

AgentMesh 是一个面向真实业务场景设计的 **多智能体执行平台 / Agent Runtime Platform**。

项目关注的重点不是简单封装一次 LLM 调用，而是解决 Agent 在真实任务执行过程中面临的核心工程问题：

- 用户意图如何被稳定理解
- 普通对话与复杂执行任务如何正确分流
- Agent / Tool / MCP / Knowledge 能力如何动态发现
- 多步骤任务如何规划与编排
- RAG、Memory 与会话上下文如何协同
- 高风险 Tool 如何进行授权与审批
- Streaming、幂等、崩溃恢复与事件驱动执行如何保证可靠性
- 如何避免多个模块重复解释用户意图并产生控制冲突
- 如何保证跨用户、跨项目的数据和知识隔离
- 如何让 Agent 的执行过程可观测、可诊断、可治理

AgentMesh 最终形成了一套明确的执行职责模型：

```text
Semantic Core  → WHAT
Route          → WHERE
Discovery      → WHICH
Planner        → HOW
Governance     → CAN
Executor       → DO
```

并通过统一的 `ExecutionIntent` 将用户语义理解与后续执行链路解耦。

---

# 1. Architecture

AgentMesh 采用三层核心架构：

```text
React + TypeScript
        │
        │ HTTP / SSE
        ▼
Go Control Plane
        │
        │ Internal Runtime API
        ▼
Python Agent Runtime
```

整体执行流程：

```text
                           User Request
                                │
                                ▼
                        React Workspace
                                │
                           HTTP / SSE
                                │
                                ▼
                         Go Control Plane
             Auth / Session / Task / Governance
                  Persistence / Reliability
                                │
                                ▼
                    Unified Semantic Core
                                │
                                ▼
                       ExecutionIntent
                                │
                                ▼
                    Deterministic Routing
                        /               \
                       /                 \
                FAST_PATH              RUNTIME
                    │                      │
                    ▼                      ▼
             Model Provider          Discovery
                                           │
                                           ▼
                                        Planner
                                           │
                                           ▼
                                      Hybrid DAG
                                           │
                                           ▼
                              Agent / Tool / MCP / RAG
                                           │
                                           ▼
                                      Governance
                                           │
                                           ▼
                                        Executor
                                           │
                                           ▼
                                     Final Result
```

---

# 2. Unified ExecutionIntent

AgentMesh 使用统一的结构化 `ExecutionIntent` 作为一次请求的权威语义合同。

传统 Agent 系统中常见的问题是：

```text
Router 理解一次用户意图
Planner 再理解一次
Tool Selector 再判断一次
Runtime 又重新判断一次
```

多个模块分别理解 WHAT，容易导致：

- Route 与 Planner 结论不一致
- Tool 被错误选择
- Knowledge 被错误触发
- Continuation 被错误识别
- 高风险副作用请求被错误执行
- 同一个请求在不同模块出现语义漂移

AgentMesh 将这一过程统一为：

```text
User Request
      +
Trusted Context
      │
      ▼
Unified Semantic Core
      │
      ▼
ExecutionIntent
      │
      ├── Goal
      ├── Requested Effects
      ├── Capability Requirements
      ├── Knowledge Requirements
      ├── Reference Resolution
      ├── Continuation Semantics
      └── Safety / Clarification Facts
```

后续模块只消费这份权威语义结果。

```text
ExecutionIntent
      │
      ├── Route
      ├── Discovery
      ├── Planner
      └── Governance Context
```

不会再由多个模块重新解释用户真正想做什么。

---

# 3. Clear Execution Boundaries

AgentMesh 将一次 Agent 请求拆分成六类职责。

| Layer | Responsibility |
|---|---|
| Semantic Core | WHAT — 用户真正想完成什么 |
| Route Derivation | WHERE — FAST_PATH 或 RUNTIME |
| Capability Discovery | WHICH — 需要哪些 Agent / Tool / MCP / Knowledge |
| Planner | HOW — 如何拆解和执行任务 |
| Governance | CAN — 当前能力是否允许执行 |
| Executor | DO — 真正执行并交付结果 |

核心原则：

```text
Semantic Core 决定 WHAT
Planner 不重新判断 WHAT
Discovery 不重新判断 WHAT
Governance 不接受模型绕过
Executor 不参与语义决策
```

这样可以减少多个控制模块之间的冲突。

---

# 4. FAST_PATH and RUNTIME

AgentMesh 保留两条顶层执行路径：

```text
                ExecutionIntent
                      │
              Route Derivation
                /            \
               /              \
         FAST_PATH           RUNTIME
```

## FAST_PATH

适合：

- 普通问答
- 日常聊天
- 简单知识解释
- 不依赖 Tool
- 不依赖 MCP
- 不依赖项目知识
- 不需要 Agent 编排
- 不包含真实副作用

流程：

```text
Request
   │
   ▼
Semantic Core
   │
   ▼
ExecutionIntent
   │
   ▼
FAST_PATH
   │
   ▼
Model Provider
   │
   ▼
Streaming Result
```

FAST_PATH 避免所有简单请求都进入完整 Runtime，降低：

- 延迟
- Token 消耗
- Runtime 开销
- 不必要的 Agent 调度

---

## RUNTIME

当请求需要：

- Tool
- MCP
- Knowledge
- RAG
- Agent
- 多步骤任务
- 文件操作
- 外部系统
- 副作用执行
- 复杂任务编排

则进入 Runtime。

```text
ExecutionIntent
      │
      ▼
Discovery
      │
      ▼
Planner
      │
      ▼
DAG
      │
      ▼
Agent / Tool / MCP / RAG
      │
      ▼
Governance
      │
      ▼
Execution
```

---

# 5. Capability Discovery

Semantic Core 不绑定具体资源 ID。

例如用户说：

```text
帮我读取项目中的配置文件
```

Semantic Core 只描述：

```text
需要文件读取能力
```

而不是：

```text
调用 Tool ID = 17
```

进入 Runtime 后由 Discovery 根据当前运行环境动态解析：

```text
Capability Requirement
        │
        ▼
Capability Discovery
        │
        ├── Agent
        ├── Tool
        ├── MCP
        ├── Knowledge
        └── Runtime Capability
```

这样可以避免 Semantic Layer 与具体基础设施耦合。

---

# 6. Planner and Hybrid DAG

对于复杂任务，Planner 将 ExecutionIntent 转换为执行计划。

例如：

```text
分析项目文档
→ 查找相关知识
→ 调用工具
→ 生成结果
```

可以形成：

```text
        Step A
       /      \
      ▼        ▼
   Step B    Step C
       \      /
        ▼    ▼
        Step D
```

Planner 只负责：

```text
HOW
```

不会重新定义：

```text
WHAT
```

Runtime 支持：

- 多步骤执行
- 顺序任务
- 并行任务
- DAG 编排
- Agent 调度
- Tool Loop
- Capability Re-discovery
- Execution Validation

---

# 7. Multi-Agent Collaboration

AgentMesh 属于 **任务编排型多智能体协作平台**。

系统不是让多个 Agent 无限制自由对话，而是通过 Runtime 对 Agent 进行：

```text
任务分解
   ↓
能力匹配
   ↓
Agent 选择
   ↓
任务调度
   ↓
执行
   ↓
结果聚合
```

Agent 由 Runtime 根据当前任务进行选择，而不是由前端或用户手动绑定执行流程。

这种方式更适合：

- 企业 Agent
- Workflow Agent
- Tool Agent
- Research Agent
- Coding Agent
- Multi-step Automation

---

# 8. Tool System

AgentMesh 提供统一 Tool 执行链路。

```text
ExecutionIntent
      │
      ▼
Discovery
      │
      ▼
Tool Selection
      │
      ▼
Governance
      │
      ▼
Tool Execution
      │
      ▼
Tool Result
      │
      ▼
Agent Loop
```

Tool 可以包含：

- Local Tool
- HTTP Tool
- File Tool
- External Service Tool
- Business Tool
- MCP Tool

所有 Tool 调用统一经过治理和执行链路，而不是让模型直接绕过平台调用。

---

# 9. MCP Integration

AgentMesh 支持 MCP Server。

Runtime 可以：

```text
Discover MCP Server
        │
        ▼
Discover MCP Tools
        │
        ▼
Capability Matching
        │
        ▼
Planner
        │
        ▼
MCP Invocation
```

MCP 能力进入 AgentMesh 后仍然受到：

- ExecutionIntent
- Discovery
- Planner
- Governance
- Trace
- Runtime

统一管理。

---

# 10. RAG and Project Knowledge

AgentMesh 支持项目级 Knowledge 与 RAG。

终端用户不需要知道“知识库”这个概念。

例如用户只需要问：

```text
这个项目的退款规则是什么？
```

系统会根据：

```text
ExecutionIntent
+
Project Context
+
Authorization Scope
```

自动判断是否需要 Knowledge。

```text
User Query
    │
    ▼
ExecutionIntent
    │
    ▼
Knowledge Required?
    │
   YES
    │
    ▼
Knowledge Scope Resolution
    │
    ▼
RAG Retrieval
    │
    ▼
Evidence
    │
    ▼
Answer
```

Knowledge Scope 支持：

```text
Global Knowledge
Project Knowledge
User / Project Authorization
```

并进行跨用户和跨项目隔离。

---

# 11. Memory

AgentMesh 将 Memory 与 Project Knowledge 分开。

```text
Memory
→ User-global

Project Knowledge
→ Project-scoped
```

Memory 可以保存长期用户信息，而项目知识用于：

```text
项目文档
业务知识
项目资料
项目配置
```

Memory Pipeline 支持：

```text
Conversation
   │
   ▼
Memory Extraction
   │
   ▼
Deduplication
   │
   ▼
Persistence
   │
   ▼
Future Retrieval
```

并考虑：

- Memory 去重
- 用户隔离
- 写入失败隔离
- 同回合避免错误自召回
- Conversation Memory Capsule
- 历史会话恢复

---

# 12. Semantic Clarification

AgentMesh 区分：

```text
语义不明确
```

与：

```text
Runtime 执行暂停
```

这是两个完全不同的概念。

例如：

```text
把它删掉
```

如果可信上下文中无法确认唯一目标：

```text
Ambiguous Target
      │
      ▼
Clarification
      │
      ▼
COMPLETED
```

系统不会：

```text
猜目标
调用 delete
创建 Approval
执行副作用
```

而是要求用户明确目标。

---

# 13. Runtime Suspension

真正已经进入 Agent / Tool 执行后，如果任务需要：

```text
补充信息
```

或者：

```text
用户授权
```

才进入执行暂停状态：

```text
INPUT_REQUIRED
AUTH_REQUIRED
      +
Real Continuation
```

之后可以：

```text
Resume
```

继续原来的 Runtime。

因此：

```text
Semantic Clarification
≠
Runtime Suspension
```

---

# 14. Governance and Approval

AgentMesh 不允许模型自行决定高风险操作是否可以执行。

Governance 负责：

```text
CAN
```

例如：

```text
删除文件
修改数据
发送外部消息
执行外部副作用
```

执行流程：

```text
Tool Request
     │
     ▼
Risk Detection
     │
     ▼
Governance
     │
     ├── ALLOW
     │
     ├── DENY
     │
     └── AUTH_REQUIRED
```

需要用户确认时：

```text
AUTH_REQUIRED
      │
      ▼
Approval
      │
   ┌──┴──┐
   │     │
ALLOW   REJECT
```

拒绝后不会产生实际副作用。

---

# 15. Dangerous Reference Protection

对于危险副作用请求：

```text
把它删掉
```

如果没有唯一可信目标：

```text
No Unique Target
      │
      ▼
Clarification
```

不会提前：

```text
选择 delete Tool
执行 delete
猜测历史目标
```

如果存在多个候选目标，也必须先澄清。

这是 AgentMesh 的 Fail-Closed 原则之一。

---

# 16. Streaming

AgentMesh 支持实时 Streaming。

```text
Model
  │
  ▼
Python Runtime
  │
  ▼
Go Control Plane
  │
  ▼
SSE
  │
  ▼
React Workspace
```

Streaming 与最终任务状态分开管理。

这样可以同时支持：

- Token 实时输出
- Runtime Trace
- Tool Result
- Task Status
- Final Result

---

# 17. Durable Runtime

AgentMesh 支持持久化 Runtime。

任务生命周期不会完全依赖单个 HTTP 请求。

核心模型：

```text
Task
  │
  ▼
Runtime Job
  │
  ▼
Worker
  │
  ▼
Execution
```

支持：

- Durable Task
- Worker Heartbeat
- Lease
- Fence
- Retry
- Recovery
- Replay Protection

---

# 18. Lease and Fencing

为了防止 Worker 崩溃后旧 Worker 再次写回结果，AgentMesh 使用：

```text
Lease
+
Fence Token
```

执行逻辑：

```text
Worker A
Fence = 1
   │
   ├── crash
   │
   ▼
Lease Expired
   │
   ▼
Worker B
Fence = 2
```

如果 Worker A 恢复并尝试写结果：

```text
Fence 1 < Fence 2
```

旧结果会被拒绝。

从而避免：

- stale worker overwrite
- duplicate completion
- stale side effect result

---

# 19. Event-Driven Runtime

AgentMesh 支持 Kafka 驱动的 Runtime 事件链。

```text
Task
 │
 ▼
Outbox
 │
 ▼
Kafka
 │
 ▼
Worker
 │
 ▼
Execution
 │
 ▼
Result Event
```

用于提升：

- 解耦能力
- Runtime 可靠性
- Worker 恢复能力
- 任务事件追踪能力

并考虑：

- Producer Failure
- Broker Outage
- Replay
- Offset
- Duplicate Event
- Crash Recovery

---

# 20. Idempotency

AgentMesh 对任务提交和执行考虑幂等语义。

同一个逻辑请求不会因为：

```text
网络重试
页面刷新
客户端重复提交
Runtime Replay
```

而产生多次业务执行。

通过：

```text
Client Request ID
+
Request Fingerprint
+
Durable Task
+
Execution State
```

共同保证任务一致性。

---

# 21. Conversation Reliability

AgentMesh 支持长会话历史。

包括：

- Conversation Persistence
- History Pagination
- Refresh Recovery
- Redis Loss Recovery
- Memory Capsule
- Durable Message History
- Conversation Anchor Preservation

Redis 只作为缓存 / 加速层使用。

关键历史数据不会只存在 Redis 中。

---

# 22. Observability

AgentMesh 将最终回答和内部执行 Trace 分离。

用户主要看到：

```text
Answer
```

而开发者可以通过 Run Details 查看：

```text
Semantic
Route
Discovery
Planner
Agent
Tool
MCP
RAG
Governance
Runtime
Cost
Latency
```

这样可以用于：

- Debug
- Root Cause Analysis
- Tool Diagnosis
- Agent Diagnosis
- Runtime Diagnosis
- Governance Audit

---

# 23. Run Details

Run Details 用于查看单次任务执行链路。

可以观察：

```text
Execution Route
ExecutionIntent
Selected Agents
Tool Calls
Runtime Trace
DAG
Knowledge
Approval
Token
Cost
Latency
```

Workspace 保持面向最终用户的简洁界面。

运行诊断信息独立放在 Run Details 中。

---

# 24. BYOK

AgentMesh 支持用户配置自己的模型服务。

可以根据配置连接不同 Model Provider。

Model Provider 与 Agent Runtime 解耦：

```text
Runtime
   │
   ▼
Model Provider Interface
   │
   ├── OpenAI Compatible
   ├── DashScope
   └── Other Providers
```

方便扩展不同模型。

---

# 25. Technology Stack

## Frontend

```text
React
TypeScript
Vite
SSE
```

负责：

- Workspace
- Conversation
- Run Details
- Governance UI
- Approval UI
- Knowledge UI
- Agent / Tool Management

---

## Control Plane

```text
Go
Gin
MySQL
Redis
Kafka
JWT
```

负责：

- Authentication
- Session
- Conversation
- Task
- Execution Route Consumption
- Governance
- Approval
- Persistence
- Durable Runtime
- Idempotency
- Streaming
- Reliability

---

## Agent Runtime

```text
Python
FastAPI
Pydantic
```

负责：

- Semantic Core
- ExecutionIntent
- Agent Runtime
- Capability Discovery
- Planner
- Replanner
- Tool Loop
- MCP
- RAG
- Memory
- Runtime Execution
- Model Provider

---

## Infrastructure

```text
MySQL
Redis
Kafka
Milvus
Docker
```

---

# 26. Project Structure

```text
AgentMesh/
│
├── backend-go/
│   ├── cmd/
│   └── internal/
│       ├── handler/
│       ├── runtime/
│       ├── service/
│       ├── repository/
│       └── model/
│
├── runtime-python/
│   └── app/
│       ├── capabilities/
│       ├── planning/
│       ├── semantics/
│       ├── services/
│       ├── tools/
│       ├── memory/
│       └── ...
│
├── web-react/
│   └── src/
│       ├── features/
│       ├── components/
│       └── ...
│
└── ...
```

---

# 27. Request Lifecycle

一个典型请求的生命周期：

```text
User
 │
 ▼
React Workspace
 │
 ▼
Go Control Plane
 │
 ├── Authentication
 │
 ├── Conversation
 │
 └── Trusted Context
 │
 ▼
Python Semantic Core
 │
 ▼
ExecutionIntent
 │
 ▼
Route Derivation
 │
 ├──────────── FAST_PATH
 │                 │
 │                 ▼
 │              Model
 │
 └──────────── RUNTIME
                   │
                   ▼
               Discovery
                   │
                   ▼
                Planner
                   │
                   ▼
                  DAG
                   │
                   ▼
          Agent / Tool / MCP
                   │
                   ▼
              Governance
                   │
                   ▼
               Executor
                   │
                   ▼
                 Result
                   │
                   ▼
                  SSE
                   │
                   ▼
                React
```

---

# 28. Design Principles

AgentMesh 的核心设计原则：

### One Semantic Source of Truth

一次请求只有一个权威 ExecutionIntent。

### Fail Closed

危险操作无法确认时，不猜测、不执行。

### Capability Dynamic Discovery

Semantic 不绑定具体资源。

### Governance Is Independent

模型无法绕过治理层。

### Planner Only Plans

Planner 不重新解释用户意图。

### Durable Before Convenient

关键任务状态优先保证可靠持久化。

### Redis Is Not the Source of Truth

缓存丢失不能导致核心会话数据丢失。

### Side Effects Require Control

真实副作用必须经过治理链路。

### Observability Is a First-Class Capability

Agent 的执行过程必须可追踪、可诊断。

---

# 29. Why AgentMesh

很多 Agent Demo 的核心流程是：

```text
Prompt
  ↓
LLM
  ↓
Tool
  ↓
Answer
```

AgentMesh 关注的是当这条链真正进入生产环境以后会发生什么：

```text
模型选错工具怎么办？

用户说“把它删了”，系统怎么知道“它”是谁？

Agent 执行一半需要用户授权怎么办？

Worker 崩溃以后谁继续任务？

旧 Worker 恢复后写入旧结果怎么办？

Kafka 暂时不可用怎么办？

用户刷新浏览器以后 Streaming 怎么恢复？

Redis 数据丢失以后 Conversation 怎么恢复？

RAG 如何保证项目之间隔离？

Planner 和 Router 判断不一致怎么办？

多个模块重复理解用户意图怎么办？

高风险 Tool 怎么防止模型绕过审批？
```

AgentMesh 的目标就是围绕这些问题构建一套完整的 Agent Runtime 与控制平面。

---

# 30. Current Capabilities

当前 AgentMesh 已实现：

- Unified Semantic Core
- Structured ExecutionIntent
- FAST_PATH / RUNTIME Routing
- Capability Discovery
- Multi-Agent Runtime
- Dynamic Planner
- Hybrid DAG
- Tool Execution
- Tool Loop
- MCP Integration
- RAG
- Project Knowledge
- User Memory
- Conversation Memory Capsule
- Model Provider / BYOK
- Streaming
- Governance
- Approval
- Semantic Clarification
- Dangerous Side-Effect Protection
- Durable Runtime
- Idempotency
- Worker Lease
- Fence Token
- Kafka Event Runtime
- Crash Recovery
- Conversation Recovery
- Cross-user Isolation
- Project Knowledge Isolation
- Runtime Trace
- Run Details
- Cost / Token / Latency Observation

---

# 31. Project Positioning

AgentMesh 更接近：

```text
Agent Runtime Platform
+
Multi-Agent Orchestration Platform
+
AI Control Plane
```

而不是单纯：

```text
Chatbot
```

或：

```text
Prompt Wrapper
```

它主要探索的是：

> 如何把大模型的不确定推理能力，与传统后端系统的确定性、安全性、可靠性和治理能力结合起来。

---

# 32. Summary

AgentMesh 的核心目标可以概括为：

```text
Understand
    ↓
Decide
    ↓
Discover
    ↓
Plan
    ↓
Govern
    ↓
Execute
    ↓
Observe
    ↓
Recover
```

其中最重要的架构边界是：

```text
Semantic Core  → WHAT
Route          → WHERE
Discovery      → WHICH
Planner        → HOW
Governance     → CAN
Executor       → DO
```

通过统一 ExecutionIntent、动态能力发现、Planner、Governance、Durable Runtime 和可观测执行链路，AgentMesh 将 Agent 从一次简单模型调用扩展为一个具备：

```text
可执行
可治理
可恢复
可观测
可扩展
```

能力的完整 Agent Runtime Platform.
