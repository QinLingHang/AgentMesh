# AgentMesh P37 OpenJiuwen Agent 适配器执行方案

文档版本:V1.0

功能基线:AgentMesh P37 Agent Harness 需求文档 V1.0

## 1 方案定位

本方案以现有 AgentMesh P37 Agent Harness 需求文档为功能基线,仅补充 OpenJiuwen Agent 的接入和执行方式。

用户需求作为本方案的实现约束:

- 现有 Internal Agent 不修改行为;
- 新增独立的 OpenJiuwen Agent 适配器;
- 通过统一的 AgentExecutor 接口执行;
- Tool、MCP、RAG 继续复用 AgentMesh 现有能力;
- Harness 负责统一观测、校验、审批和恢复;
- 不新增独立的 OpenJiuwen 执行服务;
- 不直接修改 README 或原需求文档。

最终文档生成到:`codex-generate/AgentMesh_P37_OpenJiuwen_Agent_适配器执行方案_V1.0.docx`。

## 2 总体设计结论

OpenJiuwen 不复用现有 InternalAgentPlugin,而是作为一个并列的 AgentExecutor 实现。

```text
protocol=internal
executorType=native       -> InternalAgentPlugin
executorType=openjiuwen   -> OpenJiuwenAgentExecutor
```

字段职责明确区分:

- `protocol`:表示 Agent 的调用边界,例如 `internal`、`http`、`a2a`;
- `executorType`:表示具体执行框架,例如 `native`、`openjiuwen`;
- `provider`:继续表示模型服务商,不用于执行器路由;
- `endpoint`:继续表示 Agent 的地址或标识。

这样可以保证:

- 原有 Agent 没有 `executorType` 时默认使用 `native`;
- 现有 InternalAgentPlugin 的代码和行为不变;
- OpenJiuwen 后续可以继续扩展为其他执行器;
- Resolver、Harness、日志和报告可以统一识别执行器类型。

## 3 接口和数据结构调整

### 3.1 Agent 配置

新增可选字段:

```json
{
  "protocol": "internal",
  "executorType": "openjiuwen"
}
```

默认值:`executorType = native`。

Python 内部字段使用 `executor_type`,对外 JSON 使用 `executorType`,数据库字段使用 `executor_type`。

正式方案增加一项向后兼容的数据库字段:

```sql
executor_type VARCHAR(32) NOT NULL DEFAULT 'native'
```

已有 Agent 自动使用 `native`,不需要修改已有数据内容和行为。

### 3.2 AgentExecutor 接口

继续使用现有统一接口:

```text
AgentExecutionRequest
    - agent
    - capability
    - task
    - tool_registry
    - model_runtime
    - attachments
    - on_model_event
    - on_tool_event
    - on_runtime_event

AgentExecutionResult
    - content
    - metadata
```

新增适配器必须满足:

```text
OpenJiuwenAgentExecutor implements AgentExecutor
```

不修改现有 InternalAgentPlugin 的执行逻辑。

### 3.3 Resolver 路由

Resolver 从只接收 `protocol` 调整为接收完整 `AgentProfile`,按 `protocol + executorType` 选择执行器。

路由规则:

| protocol | executorType | 执行器 |
|---|---|---|
| internal | native 或空 | 现有 InternalAgentPlugin |
| internal | openjiuwen | OpenJiuwenAgentExecutor |
| http | native 或空 | 现有 HTTP Agent |
| a2a | native 或空 | 现有 A2A Agent |
| langgraph | native 或空 | 现有 LangGraph Agent |
| 非 internal | openjiuwen | 配置错误,明确返回不支持 |

引擎中所有原来只传递 `agent.protocol` 的 Resolver 调用点都改为传递完整 Agent 配置,但保留默认行为。

## 4 OpenJiuwen 适配器执行流程

```text
Go API / Runtime Request
        ↓
Runtime Engine
        ↓
AgentExecutorResolver
        ↓
OpenJiuwenAgentExecutor
        ↓
OpenJiuwen Agent Runner
        ↓
Tool Wrapper
        ↓
AgentMesh ToolRegistry
        ↓
Internal / HTTP / MCP Tool
```

具体步骤如下:

1. Runtime Engine 根据 Agent 配置解析 `executorType`。
2. Resolver 返回 `OpenJiuwenAgentExecutor`。
3. 适配器读取 `AgentExecutionRequest`。
4. 使用已经准备好的 `task` 作为 OpenJiuwen 的输入。
5. 将 AgentMesh 的模型运行时转换为 OpenJiuwen 可使用的模型接口。
6. 将请求级 ToolRegistry 中的工具转换为 OpenJiuwen Tool。
7. OpenJiuwen 发起工具调用时,统一回调 AgentMesh ToolRegistry。
8. ToolRegistry 继续负责权限、参数校验、审批、超时和错误归一化。
9. 适配器将 OpenJiuwen 的模型事件、工具事件和运行事件转换为 AgentMesh 事件。
10. 将 OpenJiuwen 最终结果转换为 AgentExecutionResult。
11. Harness 根据事件执行 OBSERVE、ENFORCE 或 AUTO_REPAIR 逻辑。
12. Engine、Go 服务和现有任务元数据链路继续负责结果保存。

## 5 Tool、MCP、RAG 的适配边界

### 5.1 Tool

OpenJiuwen 侧只暴露包装后的 Tool,不允许直接执行底层实现。

```text
OpenJiuwen Tool
    -> AgentMesh ToolRegistry.authorize()
    -> AgentMesh ToolRegistry.execute()
    -> 返回结果或标准化错误
```

适配内容包括:工具名称、描述和输入 Schema;工具参数转换;工具执行结果转换;超时、取消和异常转换;工具开始、完成、失败事件;风险等级和审批状态。

OpenJiuwen 不应直接调用 Python 函数、HTTP 服务或数据库工具。

### 5.2 MCP

MCP 不在 OpenJiuwen 侧重新建立连接。继续复用现有链路:

```text
MCP Discovery
    -> ToolDefinition(protocol=mcp)
    -> AgentMesh ToolRegistry
    -> OpenJiuwen Tool Wrapper
```

这样可以保证 MCP 工具仍然受到:工具权限、项目隔离、参数校验、超时控制、Harness 观测、错误归一化、审批策略的统一管理。

### 5.3 RAG 和 Memory

RAG 不按 Tool 的方式适配。P37 MVP 中继续由 AgentMesh 负责:

1. Engine 执行知识检索;
2. 生成带证据和引用信息的上下文;
3. 将上下文写入 AgentExecutionRequest.task;
4. OpenJiuwen 只消费已经生成的任务上下文。

OpenJiuwen 侧暂时关闭:自己的 RAG 检索、自己的长期 Memory、自己的跨请求会话状态、自己的知识库权限判断。这样可以避免重复检索、知识范围绕过和引用丢失。

## 6 模型调用和 Harness 处理

### 6.1 模型归属

模型路由继续由 AgentMesh 管理。适配器新增 OpenJiuwenModelAdapter,负责把 AgentMesh 的 ResolvedModelRuntime 转换为 OpenJiuwen 的模型调用接口。

模型调用必须经过 AgentMesh 的事件边界,以便统一记录:模型请求、模型响应、Token 用量、成本、超时、模型异常、Trace 信息。

OpenJiuwen 不自行读取 AgentMesh 的模型密钥配置,也不绕过 AgentMesh 直接建立模型客户端。

### 6.2 Harness 责任边界

OpenJiuwen 适配器只负责执行和事件转换,不负责重新实现 Harness 的诊断和恢复逻辑。Harness 统一负责:OFF、OBSERVE、ENFORCE、AUTO_REPAIR;工具输入和输出校验;Step 和 Result 校验;循环检测;失败诊断;Retry、Repair、Replan 和 Terminate;总预算控制;HarnessEvent 和 HarnessReport。

OpenJiuwen 内部不启用独立的外层 Planner、Sub-Agent 调度和自动修复循环,避免出现两套预算和两套重试机制。

### 6.3 审批和中断

工具需要审批时,适配器必须抛出现有的 ToolApprovalRequired,不能转换成普通 Agent 失败。

```text
OpenJiuwen Tool Call
    -> ToolRegistry.authorize()
    -> REQUIRES_APPROVAL
    -> ToolApprovalRequired
    -> RuntimeTaskInterrupted(AUTH_REQUIRED)
    -> 用户确认
    -> 原任务继续执行
```

审批事件必须保留现有字段:approvalId、tool、protocol、riskLevel、fingerprint、脱敏后的参数。

## 7 具体实施阶段

### P0:依赖和 API 验证

锁定 OpenJiuwen SDK 版本;确认 Python 版本兼容性;验证最小 Agent 创建和执行;验证模型调用接口;验证自定义 Tool 注册;验证流式事件、取消和异常行为;增加依赖缺失时的明确错误,不允许静默降级到 Internal Agent。

### P1:配置和路由

Go Agent Model 增加 ExecutorType;Agent DTO、Repository、Service 增加字段传递;增加数据库前向迁移,默认值为 native;Python AgentProfile 增加 executor_type;Resolver 改为按完整 Agent 配置路由;更新 Engine 中所有 Resolver 调用点;为已有 Agent 保持 native 默认行为。

### P2:OpenJiuwenAgentExecutor

新增独立的 OpenJiuwen 执行器模块;实现 AgentExecutionRequest 到 OpenJiuwen 输入的转换;实现 OpenJiuwen 结果到 AgentExecutionResult 的转换;实现模型运行时桥接;支持 attachments;记录 executor 类型、Agent ID、任务 ID 和执行耗时;增加启动、完成、失败、取消日志。

### P3:Tool 和 MCP Bridge

将 ToolDefinition 转换为 OpenJiuwen Tool;所有 Tool callback 回到 ToolRegistry;接入审批异常;接入超时和取消;统一 Tool 事件;验证 Internal、HTTP、MCP 三类工具;禁止 OpenJiuwen 直接连接 MCP Server。

### P4:Harness 事件和运行链路

将模型、工具、步骤事件转换为 AgentMesh 事件;把 OpenJiuwen 事件写入 Harness Runtime;Harness 非 OFF 模式时绕过交互快路径;统一 ToolLoop、OpenJiuwen 和 Engine 的重试预算;确保未知副作用工具不会自动重试;贯通 Runtime、Go Metadata 和任务详情数据。

### P5:管理界面和运行展示

Agent 创建和编辑页面增加执行器类型;internal 协议下显示 native/openjiuwen;非 internal 协议禁止选择 openjiuwen;Run Details 显示实际执行器;显示 OpenJiuwen 的模型调用、Tool 调用和 Harness 事件;不新增完整的 OpenJiuwen 专属配置页面。

### P6:验收和发布

完成 Internal Agent 回归;完成 OpenJiuwen 纵向 Demo;完成 Tool、MCP、RAG、审批和异常场景;记录性能、耗时和失败率;先在测试环境开启 openjiuwen 类型;现有 Agent 继续默认使用 native;未安装依赖或配置错误时明确失败,不自动切换执行器。

## 8 验收场景

至少完成以下验证:

1. 原有 Internal Agent 的提示词、工具调用和结果保持不变。
2. internal + native 正确进入现有 Internal Agent。
3. internal + openjiuwen 正确进入新适配器。
4. OpenJiuwen 无工具任务可以正常返回结果。
5. OpenJiuwen 调用 get_order 或 current_time 时经过 ToolRegistry。
6. MCP 工具可以被 OpenJiuwen 调用,但不发生直连 MCP。
7. RAG 内容能够进入 OpenJiuwen 输入,引用信息保持完整。
8. 工具审批可以进入 AUTH_REQUIRED,确认后可以继续。
9. 工具超时、模型失败和 OpenJiuwen 异常能够统一归类。
10. OBSERVE 只记录问题,ENFORCE 可以阻断违规调用。
11. Harness 总预算不会被 OpenJiuwen 内部重试重复消耗。
12. OpenJiuwen 依赖缺失时返回明确错误。
13. HTTP、A2A、LangGraph Agent 的既有路由不受影响。
14. OpenJiuwen 事件和最终结果可以进入现有 Runtime/Go 任务记录。

## 9 明确不纳入本次适配范围

- 不修改 InternalAgentPlugin 的内部执行流程;
- 不让 OpenJiuwen 复用 Internal Agent 的 Prompt 和 ToolLoop;
- 不让 OpenJiuwen 直接管理 MCP;
- 不在 OpenJiuwen 内重新实现 RAG 和长期 Memory;
- 不新增独立 OpenJiuwen 微服务;
- 不实现 OpenJiuwen 多 Agent 编排;
- 不实现跨重启 OpenJiuwen 会话恢复;
- 不把 provider 当作执行器类型;
- 不通过 endpoint 字符串猜测执行器类型;
- 不增加静默 fallback;
- 不修改 README。

## 10 方案默认选择

本补充方案选择"正式 executorType 字段 + 默认 native"作为长期实现方式。它会增加一个向后兼容的字段和数据库迁移,但不会改变任何已有 Internal Agent 的执行行为。
