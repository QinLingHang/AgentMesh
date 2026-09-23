#!/usr/bin/env python3
"""Run the frozen set against production P23 understanding and score both routers."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * p
    lower, upper = int(index), min(int(index) + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def is_safety(row: dict) -> bool:
    text = row["query"].casefold()
    cues = ("退款", "删除", "权限", "授权", "撤权", "审批", "跨项目", "跨租户", "支付", "写入", "refund", "delete", "permission")
    return row["scenario"] == "policy_permission" or any(cue in text for cue in cues)


GO_OWNED_HANDLINGS = {"APPROVAL_REJECT", "TASK_STATUS", "RESUME", "CANCEL"}


def trusted_continuation_state(fixture: dict) -> str:
    """Mirror the trusted context shape Go supplies to P23 preflight.

    Active task ids are authoritative for task continuation.  In their
    absence, ordinary assistant text is chat history rather than a pending
    task.  This prevents the frozen evaluator from manufacturing task state
    that production Go would not supply.
    """
    conversation = fixture.get("conversation") or {}
    active_ids = [value for value in (conversation.get("activeTaskIds") or []) if value is not None]
    if len(active_ids) == 1:
        return "ONE_PENDING"
    if len(active_ids) > 1:
        return "AMBIGUOUS"
    messages = conversation.get("messages") or []
    if any(msg.get("role") == "assistant" and str(msg.get("content") or "").strip() for msg in messages):
        return "CHAT"
    return "NONE"


def model_readable_attachments(fixture: dict) -> bool:
    """Translate deterministic fixture metadata into Go's trusted flag.

    `readableInline` is fixture-owned trusted metadata.  Browser/user claims
    never set this flag in production.  All attached inputs must have inline
    readable text for the model-only attachment path to be eligible.
    """
    attachments = fixture.get("attachments") or []
    if not attachments:
        return False
    return all(
        item.get("readableInline") is True
        and isinstance(item.get("text"), str)
        and bool(item["text"].strip())
        for item in attachments
    )

def score(name: str, cases: list[dict], predictions: list[dict]) -> dict:
    observed = {row["caseId"]: row for row in predictions}
    if set(observed) != {row["caseId"] for row in cases}:
        raise ValueError(f"{name}: prediction coverage mismatch")
    buckets: dict[str, dict] = {}
    groups = {
        "all": cases,
        "safety": [row for row in cases if is_safety(row)],
        "required_runtime": [row for row in cases if row["humanLabel"] == "RUNTIME"],
        "expected_fast_path": [row for row in cases if row["humanLabel"] == "FAST_PATH"],
    }
    for scenario in sorted({row["scenario"] for row in cases}):
        groups[f"scenario:{scenario}"] = [row for row in cases if row["scenario"] == scenario]
    for group, rows in groups.items():
        route_correct = sum(observed[r["caseId"]]["route"] in r["acceptableRoutes"] for r in rows)
        runtime_missed = sum(r["humanLabel"] == "RUNTIME" and observed[r["caseId"]]["route"] == "FAST_PATH" for r in rows)
        fast_overrouted = sum(r["humanLabel"] == "FAST_PATH" and observed[r["caseId"]]["route"] == "RUNTIME" for r in rows)
        handling_correct = sum(observed[r["caseId"]].get("handling") == r["expectedHandling"] for r in rows)
        buckets[group] = {
            "cases": len(rows), "routeCorrect": route_correct,
            "routeAccuracy": route_correct / len(rows) if rows else None,
            "requiredRuntimeMissed": runtime_missed, "fastPathOverrouted": fast_overrouted,
            "handlingCorrect": handling_correct,
            "handlingAccuracy": handling_correct / len(rows) if rows else None,
        }
    latency = [float(row.get("latencyUs", 0)) / 1000.0 for row in predictions]
    return {
        "router": name,
        "metrics": buckets,
        "latencyMs": {"p50": statistics.median(latency), "p95": percentile(latency, .95), "total": sum(latency)},
        "modelCalls": sum(int(row.get("modelCalls", 0)) for row in predictions),
        "routeSelections": dict(Counter(row["route"] for row in predictions)),
        "handlingMetricScope": "PYTHON_PREFLIGHT_ONLY",
        "goOwnedHandlingCases": sorted(
            row["caseId"] for row in cases if row.get("expectedHandling") in GO_OWNED_HANDLINGS
        ),
        "errors": [
            {"caseId": row["caseId"], "scenario": row["scenario"], "safety": is_safety(row),
             "expectedRoute": row["humanLabel"], "actualRoute": observed[row["caseId"]]["route"],
             "expectedHandling": row["expectedHandling"], "actualHandling": observed[row["caseId"]].get("handling")}
            for row in cases if observed[row["caseId"]]["route"] not in row["acceptableRoutes"]
            or observed[row["caseId"]].get("handling") != row["expectedHandling"]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("p22_predictions", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    cases = jsonl(args.dataset)
    catalog = json.loads(args.fixtures.read_text(encoding="utf-8"))
    fixtures = {row["fixtureId"]: row for row in catalog["fixtures"]}
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime-python"))
    from app.semantics.intent_understanding import TaskUnderstandingRequest, understand

    predictions = []
    for row in cases:
        fixture = fixtures[row["fixtureId"]]
        state = trusted_continuation_state(fixture)
        request = TaskUnderstandingRequest.model_validate({
            "task": row["query"], "ragMode": fixture["input"]["ragMode"],
            "hasAttachments": bool(fixture.get("attachments")),
            "modelReadableAttachments": model_readable_attachments(fixture),
            "continuationState": state,
            "allowModel": False,
        })
        started = time.perf_counter_ns()
        result = understand(request)
        elapsed = time.perf_counter_ns() - started
        predictions.append({
            "caseId": row["caseId"], "route": result.execution_route,
            "handling": result.disposition, "latencyUs": elapsed / 1000,
            "modelCalls": result.model_calls, "modelTokens": result.model_tokens,
            "analysisSource": result.analysis_source, "reasonCodes": result.reason_codes,
            "source": "P23_PYTHON_PRODUCTION_UNDERSTAND_RULE_ONLY",
        })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    p23_path = args.output_dir / "p23_predictions.jsonl"
    p23_path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in predictions), encoding="utf-8")
    report = {
        "conditions": {
            "sameDataset": args.dataset.name,
            "sameFixtures": args.fixtures.name,
            "p23ModelMode": "RULE_ONLY_NO_AUTHORIZED_MODEL_CONFIG",
            "fixtureAdapter": "GO_TRUSTED_CONTEXT_V1_1",
            "handlingMetricScope": "PYTHON_PREFLIGHT_ONLY_NOT_AUTHORITATIVE_FOR_GO_TASK_OPERATIONS",
        },
        "p22": score("P22", cases, jsonl(args.p22_predictions)),
        "p23": score("P23", cases, predictions),
    }
    report_path = args.output_dir / "router_eval_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "p22": report["p22"]["metrics"]["all"],
                      "p23": report["p23"]["metrics"]["all"],
                      "p23Safety": report["p23"]["metrics"]["safety"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
