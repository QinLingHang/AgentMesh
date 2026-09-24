#!/usr/bin/env python3
"""Merge Python preflight predictions with Go-authoritative task-operation evidence.

The Execution Routing router is binary, but final Handling has split ownership. Python preflight
owns ordinary EXECUTE/CLARIFY/REJECT semantics. Go owns operations on existing
Task/Approval state: TASK_STATUS, RESUME, CANCEL and APPROVAL_REJECT.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

GO_OWNED = {"TASK_STATUS", "RESUME", "CANCEL", "APPROVAL_REJECT"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def is_safety(row: dict) -> bool:
    text = row["query"].casefold()
    cues = ("退款", "删除", "权限", "授权", "撤权", "审批", "跨项目", "跨租户", "支付", "写入", "refund", "delete", "permission")
    return row["scenario"] == "policy_permission" or any(cue in text for cue in cues)


def metrics(rows: list[dict], observed: dict[str, str]) -> dict:
    correct = sum(observed[row["caseId"]] == row["expectedHandling"] for row in rows)
    return {"cases": len(rows), "handlingCorrect": correct, "handlingAccuracy": correct / len(rows) if rows else None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("execution_routing_predictions", type=Path)
    parser.add_argument("go_authoritative_report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    cases = read_jsonl(args.dataset)
    python_rows = {row["caseId"]: row for row in read_jsonl(args.execution_routing_predictions)}
    go_report = json.loads(args.go_authoritative_report.read_text(encoding="utf-8"))
    go_rows = {row["caseId"]: row for row in go_report.get("cases", [])}

    required_go = {row["caseId"] for row in cases if row["expectedHandling"] in GO_OWNED}
    if set(go_rows) != required_go:
        missing = sorted(required_go - set(go_rows))
        extra = sorted(set(go_rows) - required_go)
        raise SystemExit(f"Go authoritative coverage mismatch: missing={missing} extra={extra}")
    failed_go = sorted(case_id for case_id, row in go_rows.items() if not row.get("passed"))
    if failed_go:
        raise SystemExit(f"Go authoritative Handling has failed cases: {failed_go}")
    if set(python_rows) != {row["caseId"] for row in cases}:
        raise SystemExit("Python prediction coverage mismatch")

    final: dict[str, str] = {}
    evidence: list[dict] = []
    for row in cases:
        case_id = row["caseId"]
        expected = row["expectedHandling"]
        if expected in GO_OWNED:
            actual = go_rows[case_id]["actualHandling"]
            source = "GO_AUTHORITATIVE_TASK_OPERATION"
        else:
            actual = python_rows[case_id].get("handling")
            source = "PYTHON_PREFLIGHT"
        final[case_id] = actual
        evidence.append({
            "caseId": case_id,
            "expectedHandling": expected,
            "actualHandling": actual,
            "source": source,
            "correct": actual == expected,
        })

    safety = [row for row in cases if is_safety(row)]
    report = {
        "schemaVersion": "execution-routing.handling.combined.v1",
        "ownership": {
            "python": "EXECUTE/CLARIFY/REJECT semantic preflight",
            "go": sorted(GO_OWNED),
        },
        "all": metrics(cases, final),
        "safety": metrics(safety, final),
        "goOwned": metrics([row for row in cases if row["expectedHandling"] in GO_OWNED], final),
        "errors": [row for row in evidence if not row["correct"]],
        "evidence": evidence,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.output), "all": report["all"], "safety": report["safety"], "goOwned": report["goOwned"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
