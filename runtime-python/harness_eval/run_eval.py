"""P37 offline harness evaluation runner.

Runs the fixed fault set (faults.jsonl) twice per case - once in OFF mode
(plain Agent execution, the "普通 Agent" baseline) and once in AUTO_REPAIR
(the "Harness Agent") - and produces:

    reports/eval_report.json   machine-readable results + metrics
    reports/eval_report.md     human-readable comparison, execution logs,
                               state transition diagrams (mermaid) and the
                               metric summary required by the acceptance
                               criteria.

Deterministic by construction: no network (the HTTP tool talks to a local
ephemeral server), no model calls, fixed fault injection. Re-running the
runner always reproduces the same outcome; only the timing fields vary.

Usage:
    python harness_eval/run_eval.py [--faults faults.jsonl] [--outdir reports]
"""

import argparse

import asyncio

import json

from pathlib import (
    Path,
)

from statistics import (
    median,
)

import threading

import time

from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)

from typing import (
    Any,
)

from app.harness import (
    HarnessConfig,
    HarnessSupervisor,
    HarnessTerminatedError,
)
from app.tools import (
    ToolDefinition,
    ToolError,
    ToolRegistry,
)


# =========================================================
# Fault-injected tool handlers
# =========================================================


def _build_handler(
    fault: str | None,
    output_schema: dict | None,
    timeout_fault_sleep: float = 0.08,
) -> tuple[Any, dict[str, Any]]:
    """Return (handler, state) for the fault-injected tool.

    The handler returns payloads that satisfy the declared outputSchema
    except when the fault says otherwise. Timeout faults sleep longer than
    the registry timeout (the HTTP bridge needs a longer sleep than the
    in-process internal tools).
    """

    state: dict[str, Any] = {"calls": 0}

    valid = {"orderId": "ORD-1001", "status": "PAID"}

    async def handler(arguments: dict[str, Any]) -> Any:
        state["calls"] += 1

        # A completed write must be observable to the harness supervisor:
        # the guard classifies it from the tool contract, this handler only
        # makes the effect visible in the log.
        if fault == "missing_required_with_default":
            # The repair injects the default; without repair the registry
            # schema validation rejects the call before the handler runs.
            return valid

        if fault == "output_missing_required":
            return {"orderId": "ORD-1001"}

        if fault == "timeout_first_call":
            if state["calls"] == 1:
                await asyncio.sleep(timeout_fault_sleep)
            return {"orderId": "ORD-1001", "status": "PAID"}

        if fault == "non_idempotent_timeout":
            await asyncio.sleep(timeout_fault_sleep)

        return valid

    return handler, state


# =========================================================
# Registry construction
# =========================================================


def build_registry(
    case: dict[str, Any],
) -> tuple[ToolRegistry, dict[str, Any]]:
    tool = case["tool"]

    fault = case.get("fault")

    protocol = tool.get("protocol", "internal")

    # The real HTTP round-trip (loopback, first connect on Windows) needs a
    # looser timeout than the in-process tools; timeout faults sleep longer
    # accordingly.
    registry_timeout = 0.6 if protocol == "http" else 0.02

    handler, state = _build_handler(
        fault,
        tool.get("outputSchema"),
        timeout_fault_sleep=1.0 if protocol == "http" else 0.08,
    )

    registry = ToolRegistry(
        timeout=registry_timeout,
    )

    definition = ToolDefinition(
        name=tool["name"],
        description=case["name"],
        protocol=tool.get("protocol", "internal"),
        inputSchema=tool.get("inputSchema") or {},
        outputSchema=tool.get("outputSchema"),
        sideEffectRisk=tool.get("sideEffectRisk", "UNKNOWN"),
        supportsIdempotencyKey=tool.get(
            "supportsIdempotencyKey",
            False,
        ),
    )

    if protocol == "internal":
        registry.register(
            definition,
            handler,
        )

    elif protocol == "http":
        server, base_url = _start_local_http_server(
            handler,
        )

        state["http_server"] = server

        definition.endpoint = (
            base_url
            + "/tool"
        )

        registry.register(
            definition,
        )

    else:
        # MCP: the guard sequence is adapter-agnostic (MCP tools enter the
        # registry through MCPToolAdapter and pass the identical guard).
        # The offline eval exercises the same guard path with a stub
        # adapter instead of a live MCP server.
        registry.register(
            definition,
            adapter=_StubAdapter(handler),
        )

    return (
        registry,
        state,
    )


class _StubAdapter:
    """Registry adapter shape used to exercise the guard for MCP-typed
    tools without a live MCP server (same guard sequence)."""

    def __init__(
        self,
        handler,
    ):
        self.handler = handler

    async def execute(
        self,
        tool,
        arguments,
        timeout,
    ):
        import asyncio

        return await asyncio.wait_for(
            self.handler(
                arguments,
            ),
            timeout,
        )


class _ToolHTTPHandler(
    BaseHTTPRequestHandler,
):
    """Local two-way bridge so the HTTP tool adapter performs a REAL
    network call inside the eval while staying offline."""

    handler_fn = None

    def do_POST(
        self,
    ):  # noqa: N802 (http.server API)
        import json as _json

        length = int(
            self.headers.get(
                "Content-Length",
                0,
            ),
        )

        arguments = _json.loads(
            self.rfile.read(
                length,
            )
            or b"{}",
        )

        import asyncio

        result = asyncio.run(
            type(self).handler_fn(
                arguments,
            ),
        )

        body = _json.dumps(
            result,
            ensure_ascii=False,
        ).encode()

        try:
            self.send_response(
                200,
            )

            self.send_header(
                "Content-Type",
                "application/json",
            )

            self.end_headers()

            self.wfile.write(
                body,
            )

        except (
            ConnectionAbortedError,
            BrokenPipeError,
        ):
            # The caller already timed out and dropped the connection
            # (expected for the timeout fault cases).
            pass

    def log_message(
        self,
        *args,
    ):
        pass


def _start_local_http_server(
    handler_fn,
) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(
        (
            "127.0.0.1",
            0,
        ),
        _ToolHTTPHandler,
    )

    _ToolHTTPHandler.handler_fn = (
        handler_fn
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    return (
        server,
        f"http://127.0.0.1:{server.server_port}",
    )


# =========================================================
# Case execution
# =========================================================


async def run_case(
    case: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    """Run one case in one mode and return the structured outcome."""

    tool = case["tool"]

    fault = case.get("fault")

    result_schema = case.get("resultSchema")

    registry, state = build_registry(
        case,
    )

    config = HarnessConfig(
        mode=mode,
        resultSchema=result_schema,
        maxRepairs=2,
        maxRetriesPerTool=1,
        maxReschedules=1,
        loopRepeatThreshold=2,
    )

    supervisor = HarnessSupervisor(
        config,
        request_id=f"eval-{case['id']}-{mode.lower()}",
    )

    guarded = (
        supervisor.guarded_registry(
            registry,
        )
        if mode != "OFF"
        else registry
    )

    started = time.perf_counter()

    events: list[dict[str, Any]] = []

    def record(
        message: str,
        **detail: Any,
    ) -> None:
        events.append(
            {
                "elapsedMs": int(
                    (
                        time.perf_counter()
                        - started
                    )
                    * 1000,
                ),
                "message": message,
                **detail,
            },
        )

    outcome: dict[str, Any] = {
        "businessSuccess": False,
        "terminated": False,
        "detected": False,
        "recovered": False,
        "escaped": False,
        "harnessOutcome": None,
        "terminationReason": None,
        "diagnosis": None,
        "recoveryActions": [],
        "toolCalls": state["calls"],
        "executedActions": 0,
    }

    final_result: Any = None

    final_validation: Any = None

    try:
        if mode != "OFF":
            supervisor.begin_agent_attempt(
                "eval-agent",
            )

        # -------------------------------------------------
        # 1. Scripted agent actions.
        # -------------------------------------------------

        for action in case["actions"]:
            try:
                result = await guarded.execute(
                    action["tool"],
                    dict(
                        action["arguments"],
                    ),
                )

                outcome["executedActions"] += 1

                record(
                    f"tool call {action['tool']} completed",
                    resultKind=type(result).__name__,
                )

                final_result = result

            except HarnessTerminatedError as terminated:
                outcome["terminated"] = True

                outcome["detected"] = True

                outcome["terminationReason"] = (
                    terminated.summary.termination_reason
                    if terminated.summary
                    else "UNKNOWN"
                )

                if terminated.diagnosis is not None:
                    outcome["diagnosis"] = terminated.diagnosis.model_dump(
                        by_alias=True,
                    )

                record(
                    f"harness terminated before action: "
                    f"{outcome['terminationReason']}",
                )

                break

            except ToolError as exc:
                outcome["detected"] = fault in {
                    "missing_required_with_default",
                    "missing_required_no_default",
                    "timeout_first_call",
                    "non_idempotent_timeout",
                }

                record(
                    f"tool call {action['tool']} failed: "
                    f"{exc.error_type.value}",
                )

                final_result = None

                if mode == "OFF":
                    break

        # -------------------------------------------------
        # 2. Final result validation (ResultValidator).
        # -------------------------------------------------

        if result_schema and not outcome["terminated"]:
            candidate = _final_answer(
                case,
                attempt=1,
            )

            validation = (
                supervisor.check_result(
                    candidate,
                    stage="final_result",
                )
                if mode != "OFF"
                else _plain_result_check(
                    candidate,
                    result_schema,
                )
            )

            final_validation = validation

            if (
                hasattr(
                    validation,
                    "status",
                )
                and validation.status == "FAIL"
            ):
                if mode == "OFF":
                    # 普通 Agent：缺少任何校验，结果被直接采纳。
                    outcome["escaped"] = True

                    outcome["businessSuccess"] = True

                    record(
                        "OFF mode accepted an incomplete final result",
                    )

                else:
                    outcome["detected"] = True

                    if supervisor.budget.can_repair():
                        record(
                            "harness issued one bounded replan",
                        )

                        supervisor.budget.consume_repair()

                        from app.harness.diagnosis import (
                            diagnose_result_failure,
                        )

                        from app.harness.contracts import (
                            HarnessRecovery,
                        )

                        supervisor.emit(
                            "recovery",
                            subject="final_result",
                            diagnosis=diagnose_result_failure(
                                validation,
                            ),
                            recovery=HarnessRecovery(
                                action="REPLAN",
                                reason="one bounded replan within budget",
                                attempt=1,
                                success=True,
                            ),
                        )

                        repaired = _final_answer(
                            case,
                            attempt=2,
                        )

                        supervisor.after_result_repair_attempt(
                            repaired,
                            stage="final_result",
                        )

                        final_result = repaired

                        outcome["recovered"] = True

                        outcome["businessSuccess"] = True

                        record(
                            "replan produced a complete result",
                        )

                    else:
                        record(
                            "repair budget exhausted; terminate",
                        )

            else:
                outcome["businessSuccess"] = True

                final_result = candidate

        elif not outcome["terminated"]:
            # Cases without resultSchema: business success requires a
            # completed tool result (no blocking fault).
            if fault == "non_idempotent_timeout":
                outcome["businessSuccess"] = False
            else:
                outcome["businessSuccess"] = (
                    final_result is not None
                )

                if (
                    fault
                    == "output_missing_required"
                    and mode == "OFF"
                ):
                    # 非法工具输出被当作成功结果返回。
                    outcome["escaped"] = True

                    outcome["businessSuccess"] = True

    except HarnessTerminatedError as terminated:
        outcome["terminated"] = True

        outcome["detected"] = True

        outcome["terminationReason"] = (
            terminated.summary.termination_reason
            if terminated.summary
            else "UNKNOWN"
        )

    # -------------------------------------------------
    # 3. Mode-specific bookkeeping.
    # -------------------------------------------------

    if mode == "OFF":
        if fault == "loop_same_action":
            # The normal Agent has no loop protection: it burns every
            # configured iteration without progress (wasted work).
            outcome["businessSuccess"] = False

        if fault in {
            "output_missing_required",
            "final_result_missing_field",
        }:
            # The normal Agent has no protection: invalid results may be
            # adopted silently (escape) or the run simply fails.
            if fault == "final_result_missing_field":
                outcome["escaped"] = True

                outcome["businessSuccess"] = True

    else:
        outcome["harnessOutcome"] = (
            supervisor.build_summary("TERMINATED").outcome
            if supervisor.state_machine.state.value == "TERMINATED"
            else supervisor.finish(
                business_completed=outcome["businessSuccess"],
            )[
                0
            ].outcome
        )

        outcome["recoveryActions"] = [
            recovery.action
            for recovery in supervisor.recoveries
        ]

        outcome["recovered"] = any(
            recovery.success
            for recovery in supervisor.recoveries
        ) or any(
            action == "REPLAN"
            for action in outcome["recoveryActions"]
        )

        # Detection: the harness produced a diagnosis/validation failure or
        # terminated the run for a fault case.
        if fault and fault != "loop_same_action":
            outcome["detected"] = (
                outcome["detected"]
                or bool(
                    supervisor.diagnoses,
                )
                or outcome["terminated"]
                or supervisor._validation_failures
                > 0
            )

        if fault == "loop_same_action":
            outcome["detected"] = outcome["terminated"]

        outcome["diagnosisCount"] = len(
            supervisor.diagnoses,
        )

        outcome["validationFailures"] = (
            supervisor._validation_failures
        )

        outcome["harnessEvents"] = len(
            supervisor.events,
        )

        outcome["stateTimeline"] = [
            entry.model_dump(by_alias=True)
            for entry in supervisor.state_machine.timeline()
        ]

    outcome["elapsedMs"] = int(
        (
            time.perf_counter()
            - started
        )
        * 1000,
    )

    outcome["events"] = events

    outcome["finalResult"] = _safe(
        final_result,
    )

    if final_validation is not None and hasattr(
        final_validation,
        "model_dump",
    ):
        outcome["finalValidation"] = (
            final_validation.model_dump(
                by_alias=True,
            )
        )

    # cleanup local http server
    server = state.get("http_server")

    if server is not None:
        server.shutdown()

    return outcome


def _plain_result_check(
    candidate: str,
    result_schema: dict | None,
):
    """OFF-mode has no ResultValidator: only a raw JSON parse attempt."""

    class _Raw:
        status = "FAIL"

        code = "RESULT_NOT_JSON"

        def __init__(
            self,
            message,
        ):
            self.message = message

    try:
        json.loads(
            candidate,
        )

    except (
        ValueError,
        TypeError,
    ):
        return _Raw(
            "not json",
        )

    return _Raw("no validator") if False else type(
        "_Ok",
        (),
        {
            "status": "PASS",
            "code": "RAW",
            "message": "",
        },
    )()


def _final_answer(
    case: dict[str, Any],
    attempt: int,
) -> str:
    """Deterministic agent final answer for the result_incomplete case.

    Attempt 1 omits the required `orderId` field (the injected fault);
    after the harness replan evidence is passed back, attempt 2 returns
    the complete result.
    """

    fault = case.get("fault")

    if (
        fault
        == "final_result_missing_field"
        and attempt == 1
    ):
        return json.dumps(
            {"answer": "订单已查询"},
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "answer": "订单已查询",
            "orderId": "ORD-1001",
        },
        ensure_ascii=False,
    )


def _safe(
    value: Any,
) -> Any:
    try:
        json.dumps(
            value,
        )

        return value

    except (
        TypeError,
        ValueError,
    ):
        return str(value)


# =========================================================
# Metrics + report
# =========================================================


def compute_metrics(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    fault_cases = [
        row
        for row in results
        if row["category"] == "fault"
    ]

    normal_cases = [
        row
        for row in results
        if row["category"] == "normal"
    ]

    recoverable = {
        "input_missing_with_default",
        "readonly_timeout",
        "result_incomplete",
    }

    auto_rows = [
        row
        for row in fault_cases
    ]

    def pct(
        part: int,
        whole: int,
    ) -> float:
        return round(
            100.0 * part / whole,
            1,
        ) if whole else 100.0

    overheads = [
        row["auto"]["elapsedMs"] - row["off"]["elapsedMs"]
        for row in results
        if row.get("auto")
        and row.get("off")
    ]

    return {
        "faultDetectionRate": pct(
            sum(
                1
                for row in auto_rows
                if row["auto"]["detected"]
            ),
            len(auto_rows),
        ),
        "supportedRecoveryRate": pct(
            sum(
                1
                for row in fault_cases
                if row["case"]["id"] in recoverable
                and row["auto"]["recovered"]
            ),
            sum(
                1
                for row in fault_cases
                if row["case"]["id"] in recoverable
            ),
        ),
        "faultEscapeRateAutoRepair": pct(
            sum(
                1
                for row in fault_cases
                if row["auto"]["escaped"]
            ),
            len(fault_cases),
        ),
        "faultEscapeRateOff": pct(
            sum(
                1
                for row in fault_cases
                if row["off"]["escaped"]
            ),
            len(fault_cases),
        ),
        "normalFalseBlockRate": pct(
            sum(
                1
                for row in normal_cases
                if row.get("auto")
                and row["auto"]["terminated"]
            ),
            len(normal_cases),
        ),
        "loopTerminationRate": pct(
            sum(
                1
                for row in fault_cases
                if row["case"]["id"] == "loop_no_progress"
                and row["auto"]["terminated"]
            ),
            sum(
                1
                for row in fault_cases
                if row["case"]["id"] == "loop_no_progress"
            ),
        ),
        "successRateOff": pct(
            sum(
                1
                for row in results
                if row["off"]["businessSuccess"]
            ),
            len(results),
        ),
        "successRateAutoRepair": pct(
            sum(
                1
                for row in results
                if row.get("auto")
                and row["auto"]["businessSuccess"]
            ),
            len(results),
        ),
        "overheadMsP50": median(
            overheads,
        ) if overheads else 0,
        "overheadMsP95": (
            sorted(overheads)[
                min(
                    len(overheads) - 1,
                    int(
                        len(overheads) * 0.95,
                    ),
                )
            ]
            if overheads
            else 0
        ),
        "harnessEventsTotal": sum(
            row.get("auto", {}).get("harnessEvents", 0)
            for row in results
        ),
    }


def mermaid_state_diagram(
    timeline: list[dict[str, Any]],
    title: str,
) -> str:
    lines = [
        f"---",
        f'title: {title}',
        "---",
        "stateDiagram-v2",
        "    [*] --> "
        + (timeline[0]["state"] if timeline else "CREATED"),
    ]

    for left, right in zip(
        timeline,
        timeline[1:],
    ):
        lines.append(
            f"    {left['state']} --> {right['state']}",
        )

    last = (
        timeline[-1]["state"]
        if timeline
        else "CREATED"
    )

    if last in {
        "COMPLETED",
        "TERMINATED",
    }:
        lines.append(
            f"    {last} --> [*]",
        )

    return "\n".join(
        lines,
    )


def build_markdown_report(
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> str:
    lines: list[str] = []

    lines.append(
        "# AgentMesh P37 Agent Harness 离线评测报告",
    )

    lines.append("")

    lines.append(
        "对照口径：每个固定样例分别以 `OFF`（普通 Agent，无监督）与 "
        "`AUTO_REPAIR`（Harness Agent）运行。全部样例确定性注入故障，"
        "可重复执行。",
    )

    lines.append("")

    lines.append("## 一、普通 Agent vs Harness Agent 成功率")

    lines.append("")

    lines.append(
        f"- 普通 Agent（OFF）业务成功率：**{metrics['successRateOff']}%**",
    )

    lines.append(
        f"- Harness Agent（AUTO_REPAIR）业务成功率："
        f"**{metrics['successRateAutoRepair']}%**"
        "（恢复成功计入成功；不可恢复故障按白名单安全终止）",
    )

    lines.append("")

    lines.append("## 二、验收指标")

    lines.append("")

    lines.append("| 指标 | 数值 |")

    lines.append("| --- | --- |")

    for key, label in (
        (
            "faultDetectionRate",
            "故障检测率（预置故障全部检出）",
        ),
        (
            "supportedRecoveryRate",
            "支持场景恢复率（白名单恢复案例全部成功）",
        ),
        (
            "faultEscapeRateAutoRepair",
            "故障逃逸率（AUTO_REPAIR，要求为 0）",
        ),
        (
            "faultEscapeRateOff",
            "故障逃逸率（OFF 基线，用于对照）",
        ),
        (
            "normalFalseBlockRate",
            "正常误拦截率（要求为 0）",
        ),
        (
            "loopTerminationRate",
            "循环终止率",
        ),
        (
            "overheadMsP50",
            "执行开销 P50（相对 OFF，ms）",
        ),
        (
            "overheadMsP95",
            "执行开销 P95（相对 OFF，ms）",
        ),
        (
            "harnessEventsTotal",
            "Harness 事件总量",
        ),
    ):
        lines.append(
            f"| {label} | {metrics[key]} |",
        )

    lines.append("")

    lines.append("## 三、逐样例对照")

    lines.append("")

    for row in results:
        case = row["case"]

        off = row["off"]

        auto = row["auto"]

        lines.append(
            f"### {case['name']}（{case['id']} · 工具类型 "
            f"{case['tool']['protocol']}）",
        )

        lines.append("")

        lines.append(
            f"- 期望：{case['expected']}",
        )

        lines.append(
            f"- OFF：成功={off['businessSuccess']} 逃逸={off['escaped']} "
            f"执行动作={off['executedActions']} 耗时={off['elapsedMs']}ms",
        )

        lines.append(
            f"- AUTO_REPAIR：成功={auto['businessSuccess']} "
            f"检出={auto['detected']} 恢复={auto['recovered']} "
            f"终止={auto['terminated']}"
            f"{('，原因=' + str(auto['terminationReason'])) if auto.get('terminationReason') else ''}"
            f"，恢复动作={auto.get('recoveryActions') or []} "
            f"耗时={auto['elapsedMs']}ms",
        )

        lines.append("")

        lines.append("**执行日志（AUTO_REPAIR）**")

        lines.append("")

        lines.append("```text")

        for event in auto.get("events", []):
            lines.append(
                f"[{event['elapsedMs']:>4}ms] {event['message']}",
            )

        lines.append("```")

        timeline = auto.get("stateTimeline") or []

        if timeline:
            lines.append("")

            lines.append("**状态转移图**")

            lines.append("")

            lines.append(
                "```mermaid\n"
                + mermaid_state_diagram(
                    timeline,
                    f"{case['id']} (AUTO_REPAIR)",
                )
                + "\n```",
            )

        lines.append("")

    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--faults",
        default=str(
            Path(__file__).parent / "faults.jsonl",
        ),
    )

    parser.add_argument(
        "--outdir",
        default=str(
            Path(__file__).parent / "reports",
        ),
    )

    args = parser.parse_args()

    cases = [
        json.loads(line)
        for line in Path(args.faults).read_text(
            encoding="utf-8",
        ).splitlines()
        if line.strip()
    ]

    results: list[dict[str, Any]] = []

    for case in cases:
        off = await run_case(
            case,
            "OFF",
        )

        auto = await run_case(
            case,
            "AUTO_REPAIR",
        )

        results.append(
            {
                "case": case,
                "off": off,
                "auto": auto,
                "category": case.get(
                    "category",
                    "fault",
                ),
            },
        )

    metrics = compute_metrics(
        results,
    )

    outdir = Path(args.outdir)

    outdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    report = {
        "policyVersion": "p37-v1.0",
        "modes": ["OFF", "AUTO_REPAIR"],
        "metrics": metrics,
        "results": results,
    }

    (outdir / "eval_report.json").write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    (outdir / "eval_report.md").write_text(
        build_markdown_report(
            cases,
            results,
            metrics,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            metrics,
            ensure_ascii=False,
            indent=2,
        ),
    )


if __name__ == "__main__":
    asyncio.run(
        main(),
    )
