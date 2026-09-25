from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def resolve_cli_path(value: str | os.PathLike[str], *, base: Path = ROOT) -> Path:
    """Resolve acceptance paths deterministically, independent of subprocess cwd."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def browser_env(*, mode: str, real_stack_only: bool, qa_mysql_dsn: str) -> dict[str, str]:
    return {
        "V4_1_E2E_ROUTING_MODE": mode,
        "V4_1_E2E_ROUTING_REAL_STACK_ONLY": "true" if real_stack_only else "false",
        "QA_TEST_MYSQL_DSN": qa_mysql_dsn,
    }


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_tail(data: str | bytes | None, limit: int = 12000) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")[-limit:]
    return (data or "")[-limit:]


def npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def run_gate(name: str, command: list[str], *, cwd: Path, env: dict[str, str] | None = None, required: bool = True, timeout: int = 1800) -> dict:
    started = time.time()
    merged = os.environ.copy()
    # Windows consoles default to GBK; browsers write UTF-8. Never allow a
    # diagnostics decoder failure to mask the real Chrome assertion.
    merged.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    if env:
        merged.update(env)
    try:
        completed = subprocess.run(
            command, cwd=cwd, env=merged, text=True, encoding="utf-8",
            errors="replace", capture_output=True, timeout=timeout,
        )
        status = "PASS" if completed.returncode == 0 else "FAIL"
        return {
            "name": name, "status": status, "required": required, "exitCode": completed.returncode,
            "elapsedSeconds": round(time.time() - started, 3),
            "stdoutTail": safe_tail(completed.stdout), "stderrTail": safe_tail(completed.stderr),
        }
    except OSError as exc:
        return {"name": name, "status": "BLOCKED" if required else "NOT_RUN", "required": required, "error": str(exc), "elapsedSeconds": round(time.time() - started, 3)}
    except subprocess.TimeoutExpired as exc:
        return {"name": name, "status": "FAIL", "required": required, "error": f"timeout after {timeout}s", "stdoutTail": safe_tail(exc.stdout, 4000), "stderrTail": safe_tail(exc.stderr, 4000), "elapsedSeconds": round(time.time() - started, 3)}


def validate_route_report(path: Path) -> tuple[bool, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        all_cases = data["current"]["metrics"]["all"]
        safety = data["current"]["metrics"]["safety"]
        ok = (all_cases["cases"] == 120 and all_cases["routeCorrect"] == 120
              and all_cases["requiredRuntimeMissed"] == 0 and all_cases["fastPathOverrouted"] == 0
              and safety["cases"] == 29 and safety["routeCorrect"] == 29)
        return ok, "route contract 120/120, runtime-missed=0, over-route=0, safety=29/29" if ok else "frozen route metrics did not satisfy gate"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, f"unreadable or malformed route evidence: {type(exc).__name__}"


def validate_handling_report(path: Path) -> tuple[bool, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        all_cases, safety, go = data["all"], data["safety"], data["goOwned"]
        ok = (all_cases["cases"] == 120 and all_cases["handlingCorrect"] == 120
              and safety["cases"] == 29 and safety["handlingCorrect"] == 29
              and go["cases"] == 14 and go["handlingCorrect"] == 14 and not data["errors"])
        return ok, "authoritative handling 120/120, safety 29/29, Go-owned 14/14" if ok else "authoritative handling metrics did not satisfy gate"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, f"unreadable or malformed handling evidence: {type(exc).__name__}"


def validate_performance_report(path: Path) -> tuple[bool, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        off, enabled = data["OFF"], data["ENABLED"]
        raw = data["raw"]
        off_rows, enabled_rows = raw["OFF"], raw["ENABLED"]
        def complete_sample(row: dict) -> bool:
            ttfb = row.get("ttfbMs")
            ttft = row.get("ttftMs")
            total = row.get("totalMs")
            latency_ok = (
                isinstance(ttfb, (int, float))
                and ttfb >= 0
                and isinstance(total, (int, float))
                and total >= ttfb
                # TTFT is intentionally nullable when a successful direct
                # response produces no non-empty content delta. The benchmark
                # schema already records TTFT coverage separately; a missing
                # delta must not invalidate an otherwise completed sample.
                and (ttft is None or (isinstance(ttft, (int, float)) and ttfb <= ttft <= total))
            )
            return (
                isinstance(row.get("route"), dict)
                and row["route"].get("mode") == "direct"
                and row.get("resultReceived") is True
                and latency_ok
                and row.get("modelTokenFieldObserved") is True
                and row.get("estimatedCostFieldObserved") is True
                and isinstance(row.get("modelTotalTokens"), int)
                and row["modelTotalTokens"] > 0
                and isinstance(row.get("estimatedCost"), (int, float))
                and row["estimatedCost"] >= 0
            )

        ttfb_delta = float(enabled["ttfbMs"]["p95"]) - float(off["ttfbMs"]["p95"])
        total_delta = float(enabled["totalMs"]["p95"]) - float(off["totalMs"]["p95"])
        frozen_latency_gate = ttfb_delta <= 1500.0 and total_delta <= 2000.0
        comparable = (off["samples"] >= 20 and off["samples"] == enabled["samples"]
                      and len(off_rows) == off["samples"] and len(enabled_rows) == enabled["samples"]
                      and all(complete_sample(row) for row in off_rows + enabled_rows)
                      and data.get("matchedEnvironmentConfirmed") is True
                      and bool(str(data.get("modelIdentity", "")).strip())
                      and data.get("qaAdmission") == "PASS"
                      and bool(str(data.get("qaAdmissionReason", "")).strip())
                      and frozen_latency_gate)
        if comparable:
            return True, f"matched 20+20 HTTP performance report; p95 TTFB delta={ttfb_delta:.3f}ms <=1500ms; p95 total delta={total_delta:.3f}ms <=2000ms; token/cost observed; independent QA admitted"
        return False, f"unverified/incomplete/mismatched performance evidence or frozen latency gate failed (p95 TTFB delta={ttfb_delta:.3f}ms, p95 total delta={total_delta:.3f}ms)"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, f"unreadable or malformed performance evidence: {type(exc).__name__}"


def apply_report_validation(gate: dict, path: Path, validator) -> None:
    if gate["status"] != "PASS":
        return
    valid, detail = validator(path)
    gate["status"] = "PASS" if valid else "FAIL"
    gate["evidence"] = str(path)
    gate["validation"] = detail


def aggregate_gates(gates: list[dict]) -> dict[str, dict]:
    # The per-command log is canonical. This index never turns a NOT_RUN or
    # BLOCKED prerequisite into a PASS merely because a related unit test passed.
    mapping = {
        "G01": ["G01_git_identity", "G01_git_head", "G01_git_branch"],
        "G02": ["G02_go_json_contract", "G02_python_json_contract", "G05_G08_case56_72_82_real_chrome"],
        "G03": ["G03_frozen_assets_validate", "G03_frozen_route_120"],
        "G04": ["G04_authoritative_handling_merge", "G05_G08_case56_72_82_real_chrome"],
        "G05": ["execution_routing_go_targeted", "execution_routing_python_targeted", "G05_G08_case56_72_82_real_chrome"],
        "G06": ["execution_routing_go_targeted", "full_browser_regression_off"],
        "G07": ["G07_live_authorization", "G05_G08_case56_72_82_real_chrome", "full_browser_regression_off"],
        "G08": ["G05_G08_case56_72_82_real_chrome", "full_browser_regression_off"],
        "G09": ["event_delivery_fault_injection", "G11_go_full", "G11_python_full"],
        "G10": ["G10_performance_cost"],
        "G11": ["G11_diff_check", "G11_go_full", "G11_go_server_build", "G11_go_migrate_build", "G11_python_full", "G11_react_full", "G11_react_build", "execution_routing_react_contract", "G11_driver_selftest"],
        "G12": ["G12_default_off", "G12_restart_rollback_real_chrome", "G11_go_full"],
    }
    by_name = {row["name"]: row for row in gates}
    order = ("FAIL", "BLOCKED", "NOT_RUN", "PASS")
    result = {}
    for gate, prerequisites in mapping.items():
        states = [by_name.get(name, {}).get("status", "NOT_RUN") for name in prerequisites]
        state = next((candidate for candidate in order if candidate in states), "NOT_RUN")
        result[gate] = {"status": state, "prerequisites": prerequisites}
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AgentMesh Execution Routing final acceptance driver. It never changes source, commits, pushes, or shared DB/Redis state.")
    parser.add_argument("--output-dir", default=str(ROOT / "qa-results" / "execution-routing-acceptance"))
    parser.add_argument("--browser", action="store_true", help="Run isolated Execution Routing focused real Chrome gate (56/72/82).")
    parser.add_argument("--full-browser", action="store_true", help="Also run the existing full V4.1 browser regression with Execution Routing OFF.")
    parser.add_argument("--fault-injection", action="store_true", help="Run existing Event Delivery outage/fault script when the Windows environment is prepared.")
    parser.add_argument("--knowledge-runtime-predictions", help="Frozen Knowledge Runtime predictions JSONL used for the 120-case Knowledge Runtime vs Execution Routing route comparison.")
    parser.add_argument("--performance-report", help="Matched OFF/ENABLED real-model performance JSON. Relative paths are resolved from the repository root.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    out = resolve_cli_path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    qa_mysql_dsn = os.environ.get("QA_TEST_MYSQL_DSN", "").strip()
    predictions_path = resolve_cli_path(args.knowledge_runtime_predictions) if args.knowledge_runtime_predictions else None
    performance_path = resolve_cli_path(args.performance_report) if args.performance_report else (out / "performance.json")
    gates: list[dict] = []
    run_stamp = uuid.uuid4().hex[:12]
    targeted_temp = out / f"pytest-targeted-{run_stamp}"
    full_temp = out / f"pytest-full-{run_stamp}"

    # Catch QA harness regressions before expensive real-stack work.
    gates.append(run_gate("G11_driver_selftest", [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "scripts" / "qa"), "-p", "test_execution_routing_acceptance.py"], cwd=ROOT))

    # G01/G11 source identity and hygiene.
    gates.append(run_gate("G01_git_identity", ["git", "status", "--short"], cwd=ROOT))
    gates.append(run_gate("G01_git_head", ["git", "rev-parse", "HEAD"], cwd=ROOT))
    gates.append(run_gate("G01_git_branch", ["git", "branch", "--show-current"], cwd=ROOT))
    gates.append(run_gate("G11_diff_check", ["git", "diff", "--check"], cwd=ROOT))

    # G03/G04/G06: frozen routing/handling plus the new real boundaries.
    authoritative_report = out / "go_authoritative_handling_report.json"
    gates.append(run_gate("execution_routing_go_targeted", ["go", "test", "./internal/service", "-run", "TestExecutionRouting|TestP5ApprovalLifecycleIntegration", "-count=1"], cwd=ROOT / "backend-go", env={"EXECUTION_ROUTING_HANDLING_REPORT": str(authoritative_report)}))
    gates.append(run_gate("execution_routing_python_targeted", [sys.executable, "-m", "pytest", "-q", "--basetemp", str(targeted_temp), "tests/test_execution_route_regression.py", "tests/test_execution_routing_understanding.py", "tests/test_execution_routing_real_stack.py"], cwd=ROOT / "runtime-python"))
    gates.append(run_gate("execution_routing_react_contract", ["node", "--test", "tests/execution-routing-real-stack-contract.test.mjs"], cwd=ROOT / "web-react"))
    # G02 has independent Go and Python serialization/schema negatives; the
    # focused Chrome gate below proves the actual Go→Python HTTP wire.
    gates.append(run_gate("G02_go_json_contract", ["go", "test", "./internal/service", "./internal/runtime", "-run", "TestKnowledgeRuntimeFullRuntimeRAGPolicyJSONArrays|TestKnowledgeRuntimeFullRuntimeRevocationJSONArrays|TestRuntimeDependencyCannotBecomeFastPath|TestInvalidModelOutputAndBudgetFailClosed|TestKnowledgeRuntimeRuntimeValidationDiagnosticsAreRedacted", "-count=1"], cwd=ROOT / "backend-go"))
    gates.append(run_gate("G02_python_json_contract", [sys.executable, "-m", "pytest", "-q", "--basetemp", str(out / f"pytest-contract-{run_stamp}"), "tests/test_execution_routing_understanding.py"], cwd=ROOT / "runtime-python"))

    # G07: independently exercise live authorization boundaries rather than
    # inferring them from routing/handling scores. These tests cover cross-user
    # RAG denial, snapshot-as-upper-bound revocation, current Tool/project
    # re-check and MCP project-scope re-check.
    gates.append(run_gate(
        "G07_live_authorization",
        ["go", "test", "./internal/service", "-run",
         "TestRagLiveAuthorization|TestRagV11SnapshotIsUpperBoundAfterRevocation|TestP5ApprovalLifecycleIntegration", "-count=1"],
        cwd=ROOT / "backend-go", timeout=1200,
    ))

    dataset = ROOT / "runtime-python" / "tests" / "fixtures" / "execution_routing_human_eval_v1.jsonl"
    fixtures = ROOT / "runtime-python" / "tests" / "fixtures" / "execution_routing_eval_fixtures_v1.json"
    gates.append(run_gate("G03_frozen_assets_validate", [sys.executable, str(ROOT / "scripts" / "qa" / "validate_execution_routing_human_eval.py"), str(dataset), str(fixtures)], cwd=ROOT))
    if predictions_path:
        route_out = out / "router-eval"
        gates.append(run_gate("G03_frozen_route_120", [sys.executable, str(ROOT / "scripts" / "qa" / "run_execution_routing_frozen_eval.py"), str(dataset), str(fixtures), str(predictions_path), str(route_out)], cwd=ROOT))
        apply_report_validation(gates[-1], route_out / "router_eval_report.json", validate_route_report)
    else:
        gates.append({"name": "G03_frozen_route_120", "status": "NOT_RUN", "required": True, "reason": "provide --knowledge-runtime-predictions so the frozen Knowledge Runtime/Execution Routing comparison is reproducible"})

    # Full language regressions/builds. These are intentionally required.
    # The suite creates many isolated schemas. On Windows/MySQL, package-level
    # parallelism can make unrelated schema migrations contend on metadata locks
    # and create a false 10-minute timeout. Serializing packages preserves all
    # intra-test concurrency assertions while removing cross-package DDL noise.
    gates.append(run_gate("G11_go_full", ["go", "test", "-p", "1", "-timeout", "15m", "./..."], cwd=ROOT / "backend-go", timeout=3600))
    gates.append(run_gate("G11_go_server_build", ["go", "build", "-mod=readonly", "./cmd/server"], cwd=ROOT / "backend-go"))
    gates.append(run_gate("G11_go_migrate_build", ["go", "build", "-mod=readonly", "./cmd/migrate"], cwd=ROOT / "backend-go"))
    gates.append(run_gate("G11_python_full", [sys.executable, "-m", "pytest", "-q", "--basetemp", str(full_temp)], cwd=ROOT / "runtime-python"))
    gates.append(run_gate("G11_react_full", [npm_command(), "test"], cwd=ROOT / "web-react"))
    gates.append(run_gate("G11_react_build", [npm_command(), "run", "build"], cwd=ROOT / "web-react"))

    if predictions_path and authoritative_report.exists():
        execution_routing_predictions = out / "router-eval" / "execution_routing_predictions.jsonl"
        combined = out / "combined_handling_report.json"
        if execution_routing_predictions.exists():
            gates.append(run_gate("G04_authoritative_handling_merge", [sys.executable, str(ROOT / "scripts" / "qa" / "merge_execution_routing_handling.py"), str(dataset), str(execution_routing_predictions), str(authoritative_report), str(combined)], cwd=ROOT))
            apply_report_validation(gates[-1], combined, validate_handling_report)
        else:
            gates.append({"name": "G04_authoritative_handling_merge", "status": "BLOCKED", "required": True, "reason": "Execution Routing predictions were not produced"})
    else:
        gates.append({"name": "G04_authoritative_handling_merge", "status": "NOT_RUN", "required": True, "reason": "requires frozen Execution Routing predictions and Go authoritative report"})

    # G08 focused real Chrome is opt-in because it needs MySQL/Redis/Milvus,
    # Desktop Bridge and Chrome. It starts isolated Go/Python/React processes.
    if args.browser and not qa_mysql_dsn:
        focused = {
            "name": "G05_G08_case56_72_82_real_chrome", "status": "BLOCKED", "required": True,
            "reason": "QA_TEST_MYSQL_DSN must be set before --browser; acceptance will not guess or reuse a shared database",
        }
        gates.append(focused)
    elif args.browser:
        focused = run_gate(
            "G05_G08_case56_72_82_real_chrome",
            ["node", "e2e/v4-1-browser-e2e.mjs"], cwd=ROOT / "web-react",
            env=browser_env(mode="ENABLED", real_stack_only=True, qa_mysql_dsn=qa_mysql_dsn), timeout=3000,
        )
        gates.append(focused)
        # The focused harness contains an embedded real Go process restart on
        # the same isolated DB: ENABLED creates one Durable task; the server is
        # restarted with OFF and the exact clientRequestId must replay the same
        # task without model/runtime re-execution. Mirror that embedded result
        # as an explicit G12 prerequisite instead of treating default OFF as
        # sufficient evidence.
        gates.append({
            "name": "G12_restart_rollback_real_chrome",
            "status": focused["status"],
            "required": True,
            "evidence": "embedded in G05_G08_case56_72_82_real_chrome",
            "reason": "focused Chrome includes ENABLED→Go restart→OFF exact-request replay",
        })
    else:
        gates.append({"name": "G05_G08_case56_72_82_real_chrome", "status": "NOT_RUN", "required": True, "reason": "pass --browser on prepared Windows QA environment"})
        gates.append({"name": "G12_restart_rollback_real_chrome", "status": "NOT_RUN", "required": True, "reason": "pass --browser to prove restart/rollback against one persisted Durable task"})

    if args.full_browser and not qa_mysql_dsn:
        gates.append({
            "name": "full_browser_regression_off", "status": "BLOCKED", "required": True,
            "reason": "QA_TEST_MYSQL_DSN must be set before --full-browser; acceptance will not guess or reuse a shared database",
        })
    elif args.full_browser:
        gates.append(run_gate(
            "full_browser_regression_off",
            ["node", "e2e/v4-1-browser-e2e.mjs"], cwd=ROOT / "web-react",
            env=browser_env(mode="OFF", real_stack_only=False, qa_mysql_dsn=qa_mysql_dsn), timeout=3600,
        ))
    else:
        gates.append({"name": "full_browser_regression_off", "status": "NOT_RUN", "required": True, "reason": "pass --full-browser for final closure"})

    # G09: never silently claim Kafka/outage coverage. The existing script is
    # invoked only when explicitly requested in the prepared Windows stack.
    if args.fault_injection:
        if os.name == "nt":
            gates.append(run_gate("event_delivery_fault_injection", ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "qa" / "KAFKA_FINAL_TASK_OUTAGE.ps1")], cwd=ROOT, env={"EXECUTION_ROUTING_MODE": "OFF"}, timeout=3600))
        else:
            gates.append({"name": "event_delivery_fault_injection", "status": "BLOCKED", "required": True, "reason": "Event Delivery outage harness is Windows PowerShell-specific"})
    else:
        gates.append({"name": "event_delivery_fault_injection", "status": "NOT_RUN", "required": True, "reason": "pass --fault-injection for final closure"})

    # G10 remains evidence-driven. Development supplies benchmark_execution_routing_http.py;
    # acceptance must provide the resulting report rather than inventing data.
    performance = performance_path
    if performance.exists():
        valid, detail = validate_performance_report(performance)
        admission = ""
        try:
            admission = json.loads(performance.read_text(encoding="utf-8")).get("qaAdmission", "")
        except (OSError, ValueError):
            pass
        status = "PASS" if valid else ("FAIL" if admission == "FAIL" else "BLOCKED")
        gates.append({"name": "G10_performance_cost", "status": status,
                      "required": True, "evidence": str(performance), "validation": detail})
    else:
        gates.append({"name": "G10_performance_cost", "status": "NOT_RUN", "required": True,
                      "reason": "provide --performance-report or create <output-dir>/performance.json using benchmark_execution_routing_http.py against matched OFF and ENABLED isolated stacks"})

    # G12 static mode default. Runtime rollback behavior is also exercised by
    # existing Execution Routing idempotency/mode tests in Go full regression.
    env_example = ROOT / "backend-go" / ".env.example"
    env_text = env_example.read_text(encoding="utf-8") if env_example.exists() else ""
    gates.append({"name": "G12_default_off", "status": "PASS" if re.search(r"^EXECUTION_ROUTING_MODE=OFF\s*$", env_text, re.MULTILINE) else "FAIL", "required": True})

    required_failures = [g for g in gates if g.get("required") and g["status"] != "PASS"]
    report = {
        "schemaVersion": "execution-routing.acceptance.v1",
        "root": str(ROOT),
        "inputs": {
            "outputDir": str(out),
            "knowledgeRuntimePredictions": str(predictions_path) if predictions_path else None,
            "performanceReport": str(performance) if performance.exists() else None,
            "browserRequested": bool(args.browser),
            "fullBrowserRequested": bool(args.full_browser),
            "faultInjectionRequested": bool(args.fault_injection),
            "qaMySQLConfigured": bool(qa_mysql_dsn),
        },
        "sourceFiles": {
            "envExampleSha256": sha256(env_example) if env_example.exists() else None,
            "qaCodeSha256": {
                relative: sha256(ROOT / relative) if (ROOT / relative).is_file() else None
                for relative in (
                    "web-react/e2e/v4-1-browser-e2e.mjs",
                    "scripts/qa/run_execution_routing_acceptance.py",
                    "scripts/qa/benchmark_execution_routing_http.py",
                    "backend-go/internal/service/execution_routing_real_stack_integration_test.go",
                    "runtime-python/tests/test_execution_routing_real_stack.py",
                )
            },
        },
        "gates": gates,
        "G01_G12": aggregate_gates(gates),
        "scopeNote": "G07 has an independent live-authorization gate; G09 remains real Event Delivery outage evidence; G10 requires matched OFF/ENABLED real-model evidence; G12 requires default OFF plus a real Go restart from ENABLED to OFF replaying one persisted Durable request without re-execution.",
        "summary": {
            "PASS": sum(g["status"] == "PASS" for g in gates),
            "FAIL": sum(g["status"] == "FAIL" for g in gates),
            "BLOCKED": sum(g["status"] == "BLOCKED" for g in gates),
            "NOT_RUN": sum(g["status"] == "NOT_RUN" for g in gates),
            "fullPass": not required_failures and all(x["status"] == "PASS" for x in aggregate_gates(gates).values()),
        },
    }
    report_path = out / "execution_routing_acceptance_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["summary"]["fullPass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
