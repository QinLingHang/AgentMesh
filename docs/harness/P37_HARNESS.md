# P37 Agent Harness（执行监督层）

> 状态：P0 最小可实现版本已实现。需求基线：`AgentMesh_P37_Agent_Harness_需求文档_V1.0.docx`。
> 本文覆盖配置、链路、验收、演示与常见问题。

## 1. 定位与边界

Agent Harness 是 Agent 执行链**外部**的监督层：在关键节点做确定性校验、记录脱敏证据、把失败转换为结构化诊断，并在统一预算与副作用约束内执行白名单恢复。

- 不替代 Agent、模型、规划器或工具系统；不新建第二套编排/工具/追踪/评测系统。
- Planner 决定“做什么”，Scheduler 决定“谁执行”，Harness 只监督不路由。
- 已有审批、授权、租户隔离、超时与敏感路径保护继续生效，Harness 不提供绕过入口。
- 错误证据只保存字段路径、错误码与摘要；不保存令牌、凭据、完整提示词或未脱敏响应。
- 已完成的副作用步骤（Tool/HTTP/A2A）绝不因质量原因自动重放：`RETRY` 仅限只读工具或带稳定幂等键的幂等写；`REPLAN` 在本次尝试已产生已完成写工具调用时被禁止。

## 2. 四种运行模式

| 模式 | 校验 | 阻断 | 自动恢复 | 说明 |
| --- | --- | --- | --- | --- |
| `OFF` | 不新增 | 否 | 否 | 缺省值。不传/传 OFF 时执行语义与历史行为完全一致 |
| `OBSERVE` | 执行并记录 | 否 | 否 | 灰度观察；对失败只记录，不修改调用与结果 |
| `ENFORCE` | 执行并记录 | 是 | 否 | 只阻断已定义的失败（校验失败/循环/未知写结果） |
| `AUTO_REPAIR` | 执行并记录 | 是 | 预算内执行 | 白名单动作：`REPAIR_ARGS`/`RETRY`/`FALLBACK`/`REPLAN`/`TERMINATE` |

规则：

- 配置在任务创建时冻结为不可变快照（`tasks.harness_config_json`、durable 队列 `request_json`），排队/重启/续跑/重放均使用同一快照，消费者不从当前默认值重新计算。
- 非 OFF 任务强制走完整 Runtime：`/api/tasks/run-stream` 的交互快路径在 harnessSupervised 时被跳过（`handlers.go`）。
- 统一预算：旧 ToolLoop 重试、Agent 重调度与新修复动作全部计入同一 `HarnessBudget`；AUTO_REPAIR 启用时 ToolLoopRunner 的内置重试对该请求停用（`tool_max_retries=0`），保证一个动作只由一个策略触发。

## 3. 模块地图（Python Runtime）

```
app/harness/
  contracts.py   HarnessConfig/RunState/ValidationResult/FailureDiagnosis/
                 HarnessEvent/HarnessBudget/HarnessSummary/HarnessReport
  state.py       集中状态机（非法跳转直接拒绝）
  validators.py  Pre/ToolInput/ToolOutput/Step/Result 六个确定性校验器
  loop.py        动作指纹 + 显式 progressMarker 的循环检测
  diagnosis.py   错误码→诊断的规则表（EXACT 置信度）
  recovery.py    有界 REPLAN 决策与证据回传提示词
  guard.py       GuardedToolRegistry（Internal/HTTP/MCP 统一防线）
  supervisor.py  运行主线：状态/事件/预算/模式分支/报告聚合
```

接入点：

- `RuntimeRequest.harness_config`（camelCase `harnessConfig`）→ `create_harness_supervisor()`。
- 工具调用边界：`ToolRegistry` 被包装为 `GuardedToolRegistry`，治理/发现/adapter 不变，仅监督 `execute()`。
- 结果边界：`execute_assignment` 与最终 `answer` 通过 `check_result()`；AUTO_REPAIR 结果失败触发**至多一次**有界重规划（`replan_decision` 决定允许与否）。
- 终止：`HarnessTerminatedError` 携带 summary/report，沿异常链回传（与 `find_runtime_interruption` 同一模式），在 DAG 调用点、run 收尾与 `main.py` 兜底转换为 `status=FAILED` 的结构化响应，而不是 500。
- 响应：`RuntimeResponse.harness_summary` / `harness_report`（OFF 为 null）。

## 4. Go 控制面

- 请求：`POST /api/tasks/run | run-stream | run-durable`、Public API `POST /api/tasks/run` 均接受 `harnessConfig`（`internal/model/harness.go` 定义，`Normalize()` 负责校验与默认值）。
- 持久化：`tasks.harness_config_json`（创建时冻结）；Resume 从任务行回放快照；durable 路径快照同时进 `runtime_jobs.request_json`。
- 结果：`ExecuteResponse.harness_summary/harness_report` → `RunTaskResult.harnessSummary/harnessReport`；assistant message metadata 追加 `harnessSummary/harnessReport`（P0 复用现有 JSON metadata，不新建表）。
- 兼容：旧任务/旧请求无 Harness 字段 → 按 OFF 读取；`FAILED` 状态仅在携带 harness 数据时映射为“任务 ERROR + 结构化报告返回”。

## 5. 数据库迁移（启动/`cmd/migrate` 自动执行，幂等）

| 表 | 列 | 说明 |
| --- | --- | --- |
| `tools` | `output_schema JSON NULL` | 输出校验契约；未配置时校验状态为 `NOT_CONFIGURED`，绝不记为 PASS |
| `tools` | `side_effect_risk VARCHAR(32) DEFAULT 'UNKNOWN'` | `READ_ONLY`/`IDEMPOTENT_WRITE`/`NON_IDEMPOTENT_WRITE`/`UNKNOWN`；UNKNOWN 禁止自动写重试 |
| `tools` | `supports_idempotency_key TINYINT(1) DEFAULT 0` | 幂等写安全重放门控 |
| `tools` | `fallback_tool_id VARCHAR(191) NULL` | 仅允许显式配置的替代工具 |
| `tools` | `argument_aliases JSON NULL` | 显式别名映射，不做语义猜测 |
| `agents` | `executor_type VARCHAR(32) DEFAULT 'native'` | OpenJiuwen 适配器路由字段 |
| `tasks` | `harness_config_json JSON NULL` | 冻结的 Harness 快照 |

## 6. OpenJiuwen 适配器

路由矩阵（`app/agents/resolver.py`，按完整 Agent 配置路由）：

| protocol | executorType | 执行器 |
| --- | --- | --- |
| internal | native/空 | 现有 InternalAgentPlugin（行为不变） |
| internal | openjiuwen | `agent.openjiuwen`（`app/agents/openjiuwen.py`） |
| http/a2a/langgraph | openjiuwen | 配置错误，明确拒绝 |

- 独立 `AgentExecutor` 实现：自带的有限步框架循环 + `OpenJiuwenModelAdapter`（模型调用经 AgentMesh 网关，统一模型事件/Token/成本）+ `OpenJiuwenToolBridge`（工具回调全部回到 ToolRegistry，审批抛 `ToolApprovalRequired`）。
- RAG/Memory：消费 Engine 已生成的上下文（`request.task`），OpenJiuwen 侧不自建检索/记忆，避免知识范围绕过。
- `OPENJIUWEN_EXECUTION_MODE=sdk`（生产默认，锁定
  `requirements-openjiuwen-sdk.txt` 中的 `openjiuwen==0.1.18`，并在
  FastAPI lifespan 管理全局 Runner；缺依赖/版本/API 不兼容明确失败）；
  `builtin`（仅开发/测试显式设置 `OPENJIUWEN_ALLOW_BUILTIN=true`，绝不作为
  SDK 的静默回退）。
- React：智能体创建页 internal 协议下出现“执行器类型”选择；运行详情 Harness 页签/事件中可见实际执行器。

## 7. React 展示

- 运行设置：`Harness` 模式选择（默认 OFF）+ 非 OFF 展开的预算折叠区（AUTO_REPAIR 额外显示修复次数/单工具重试上限）。
- 运行详情：`Harness` 页签（模式、结论、校验失败、诊断、恢复动作、预算消耗、状态时间线、脱敏 evidence），旧任务无数据时整页签隐藏，不伪造空报告。

## 8. 评测与演示（命题要求对照）

```bash
cd runtime-python
PYTHONPATH=. .venv/Scripts/python.exe harness_eval/run_eval.py   # Linux/macOS: python harness_eval/run_eval.py
```

- 固定样例：`harness_eval/faults.jsonl`（正常基线 + 输入缺字段/不可修复、输出不完整、只读超时、写操作状态未知、循环、结果不完整；覆盖 Internal/HTTP/MCP 三类工具边界）。
- 每样例 OFF 与 AUTO_REPAIR 各跑一次，输出 `harness_eval/reports/eval_report.{json,md}`：执行日志、mermaid 状态转移图、对照指标。
- 最近一次参考结果（本机）：故障检测率 100%、白名单恢复率 100%、AUTO_REPAIR 逃逸率 0%（OFF 基线 28.6%）、正常误拦截 0、循环终止 100%、成功率 OFF 37.5% → AUTO_REPAIR 50.0%，其余不可恢复案例按白名单安全终止并给出诊断。
- 单元/集成验证：`python -m pytest -q`（含 `tests/test_p37_harness.py`）；`go test ./...`；`npm test && npm run build`。

三类工具 Demo 路径：

1. **Internal**：注册工具后在聊天任务中触发调用（演示链路使用 `get_order`）；Harness 页签展示 Guard 校验/预算事件。
2. **HTTP**：注册 HTTP 工具（真实网络调用）；评测 runner 内置本地回环服务做离线演示。
3. **MCP**：MCP 工具经 `MCPToolAdapter` 进入同一 ToolRegistry，Guard 序列与另两类完全一致（adapter 无关）。

## 9. 常见问题（运维）

- **为什么我的任务被终止了？** 详情页 Harness 页签的 `终止原因` 与诊断给出确定性根因（如 `INPUT_VALIDATION_INPUT_REQUIRED_MISSING`、`TOOL_OUTCOME_UNKNOWN`、`LOOP_DETECTED`）；证据仅含字段路径/错误码。
- **写操作超时后为什么不能自动重试？** 请求已发送且结果未知（`TOOL_OUTCOME_UNKNOWN`）属于非幂等风险，必须人工确认；幂等写需 `supportsIdempotencyKey=true` 且请求携带 `idempotencyKey` 参数。
- **为什么校验结果显示“未配置”？** 工具未配置 `outputSchema`（或任务未配置 `resultSchema`）时状态为 `NOT_CONFIGURED`——按需求不记录为通过，也不拦截。
- **排队后改了系统默认模式，为什么没生效？** 快照在任务创建时冻结，这是验收要求（`HARNESS_DEFAULT_MODE` 只影响未携带快照的新请求）。
- **OBSERVE 会改变结果吗？** 不会：该模式下 Guard/校验器只记录（含证据），调用、参数、结果与异常与 OFF 完全一致。
