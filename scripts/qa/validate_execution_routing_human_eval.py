#!/usr/bin/env python3
"""Validate Execution Routing labels, deterministic fixture references and special contracts."""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path

ROUTES = {"FAST_PATH", "RUNTIME"}
HANDLINGS = {"EXECUTE", "CLARIFY", "REJECT", "TASK_STATUS", "RESUME", "CANCEL", "APPROVAL_REJECT"}
NO_NEW_TASK = {"TASK_STATUS", "RESUME", "CANCEL", "APPROVAL_REJECT"}
TASK_BOUND_HANDLINGS = {"TASK_STATUS", "RESUME", "CANCEL", "APPROVAL_REJECT"}
CHAT_CLARIFY_CASES = {"CONTINUATION-02", "CONTINUATION-06", "CONTINUATION-07"}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    rows = load_jsonl(args.dataset)
    catalog = json.loads(args.fixtures.read_text(encoding="utf-8"))
    fixture_rows = catalog.get("fixtures", [])
    fixture_by_id = {item.get("fixtureId"): item for item in fixture_rows}
    problems: list[str] = []
    if len(rows) != 120 or len({r.get("caseId") for r in rows}) != 120:
        problems.append("dataset must contain exactly 120 unique cases")
    if len(fixture_rows) != 120 or len(fixture_by_id) != 120:
        problems.append("fixture catalog must contain exactly 120 unique fixtures")
    for row in rows:
        cid = row.get("caseId", "<missing>")
        fid = row.get("fixtureId")
        fixture = fixture_by_id.get(fid)
        if fixture is None or fixture.get("caseId") != cid:
            problems.append(f"{cid}: missing or mismatched fixture")
            continue
        if row.get("reviewStatus") != "HUMAN_REVIEWED": problems.append(f"{cid}: not human reviewed")
        if row.get("humanLabel") not in ROUTES: problems.append(f"{cid}: invalid route")
        acceptable = row.get("acceptableRoutes")
        if not isinstance(acceptable, list) or not acceptable or row.get("humanLabel") not in acceptable or any(x not in ROUTES for x in acceptable):
            problems.append(f"{cid}: invalid acceptable routes")
        if row.get("expectedHandling") not in HANDLINGS: problems.append(f"{cid}: invalid handling")
        for field in ("requiredCapabilityKinds", "forbiddenCapabilityKinds"):
            if not isinstance(row.get(field), list): problems.append(f"{cid}: {field} must be list")
        if not row.get("reviewerId"): problems.append(f"{cid}: reviewer missing")
        try: dt.datetime.fromisoformat(str(row.get("reviewedAt", "")).replace("Z", "+00:00"))
        except ValueError: problems.append(f"{cid}: invalid reviewedAt")
        if row.get("expectedHandling") in NO_NEW_TASK and fixture.get("expectedInvariants", {}).get("createNewTask") is not False:
            problems.append(f"{cid}: operation must not create a new task")
        scenario = row.get("scenario")
        if scenario == "implicit_enterprise_knowledge" and (not fixture.get("knowledge", {}).get("authorizedBaseIds") or not fixture.get("knowledge", {}).get("documents")):
            problems.append(f"{cid}: knowledge scenario lacks deterministic authorized evidence")
        if scenario == "personal_realtime_tool" and not fixture.get("tools"):
            problems.append(f"{cid}: realtime-tool scenario lacks a deterministic tool")
        if scenario == "workflow" and cid != "WORKFLOW-11" and not fixture.get("tools"):
            problems.append(f"{cid}: workflow scenario lacks a deterministic tool")
        if scenario == "fault_recovery" and not fixture.get("tasks"):
            problems.append(f"{cid}: fault-recovery scenario lacks a deterministic task")
        if scenario == "continuation" and row.get("expectedHandling") in TASK_BOUND_HANDLINGS and not fixture.get("tasks"):
            problems.append(f"{cid}: task-bound continuation lacks a deterministic task")
        if scenario == "fault_recovery" and not fixture.get("faults"):
            problems.append(f"{cid}: fault-recovery scenario lacks an injected fault")
        if scenario == "policy_permission" and ("otherUserId" not in fixture.get("identity", {}) or "otherProjectId" not in fixture.get("identity", {})):
            problems.append(f"{cid}: permission scenario lacks cross-principal boundaries")
        expected_ref = f"{args.fixtures.name}#{fid}"
        context = row.get("syntheticContext", {})
        if context.get("historyFixtureRef") != expected_ref or context.get("resourceFixtureRef") != expected_ref:
            problems.append(f"{cid}: fixture references are not canonical")

    by_case = {row.get("caseId"): row for row in rows}
    c56, f56 = by_case.get("WORKFLOW-11", {}), fixture_by_id.get("execution-route-eval-056", {})
    if (c56.get("humanLabel"), c56.get("expectedHandling"), c56.get("requiredCapabilityKinds"), c56.get("forbiddenCapabilityKinds")) != ("FAST_PATH", "EXECUTE", [], ["TOOL"]):
        problems.append("WORKFLOW-11: uploaded-readable attachment contract mismatch")
    if len(f56.get("attachments", [])) != 2 or not all(x.get("readableInline") for x in f56.get("attachments", [])) or f56.get("tools") or not f56.get("expectedInvariants", {}).get("reportConflict"):
        problems.append("WORKFLOW-11: deterministic readable attachment fixture missing")
    if c56.get("finalization", {}).get("selectedCondition") != "READABLE_INLINE_ATTACHMENTS":
        problems.append("WORKFLOW-11: selected conditional branch is not recorded")
    for continuation_case in sorted(CHAT_CLARIFY_CASES):
        case = by_case.get(continuation_case, {})
        fixture = fixture_by_id.get(case.get("fixtureId"), {})
        conversation = fixture.get("conversation", {})
        messages = conversation.get("messages", [])
        if (case.get("humanLabel"), case.get("expectedHandling")) != ("FAST_PATH", "CLARIFY"):
            problems.append(f"{continuation_case}: chat clarification label mismatch")
        if fixture.get("tasks") or conversation.get("activeTaskIds"):
            problems.append(f"{continuation_case}: chat clarification fixture must not manufacture active task state")
        if any(message.get("taskId") is not None for message in messages):
            problems.append(f"{continuation_case}: chat clarification fixture must not contain task-linked messages")
    c72, f72 = by_case.get("CONTINUATION-12", {}), fixture_by_id.get("execution-route-eval-072", {})
    if c72.get("expectedHandling") != "APPROVAL_REJECT" or f72.get("expectedInvariants", {}).get("writeCount") != 0 or f72.get("expectedInvariants", {}).get("approvalState") != "REJECTED":
        problems.append("CONTINUATION-12: approval rejection contract mismatch")
    if c72.get("finalization", {}).get("replacesPlaceholderHandling") != "CLARIFY":
        problems.append("CONTINUATION-12: placeholder replacement is not recorded")
    c82, f82 = by_case.get("POLICY_PERMISSION-07", {}), fixture_by_id.get("execution-route-eval-082", {})
    inv82 = f82.get("expectedInvariants", {})
    if c82.get("forbiddenCapabilityKinds") != [] or inv82.get("forbiddenOperations") != ["local.fs.delete"] or inv82.get("allowedOperations") != ["local.fs.list"]:
        problems.append("POLICY_PERMISSION-07: delete-only prohibition contract mismatch")
    if collections.Counter(row.get("split") for row in rows) != {"development": 80, "holdout": 40}:
        problems.append("development/holdout split changed")
    if problems:
        print(f"INVALID: {len(problems)} problem(s)")
        for item in problems[:30]: print(" -", item)
        return 2
    dataset_hash = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    fixture_hash = hashlib.sha256(args.fixtures.read_bytes()).hexdigest()
    print(f"VALID: cases=120 fixtures=120 dataset_sha256={dataset_hash} fixtures_sha256={fixture_hash}")
    if args.freeze:
        manifest = {
            "schemaVersion": "execution-routing.eval.freeze.v1", "cases": 120,
            "dataset": args.dataset.name, "datasetSha256": dataset_hash,
            "fixtures": args.fixtures.name, "fixturesSha256": fixture_hash,
            "fixtureContractRevision": catalog.get("contractRevision", "v1"),
            "previousFixturesSha256": catalog.get("previousFixturesSha256"),
            "changeNotes": catalog.get("changeNotes", []),
            "splits": {"development": 80, "holdout": 40},
            "reviewers": sorted({row["reviewerId"] for row in rows}),
            "specialContracts": {
                "WORKFLOW-11": "READABLE_ATTACHMENTS_NO_TOOL",
                "CONTINUATION-02": "NO_ACTIVE_TASK_FAST_PATH_CLARIFY",
                "CONTINUATION-06": "NO_ACTIVE_TASK_FAST_PATH_CLARIFY",
                "CONTINUATION-07": "NO_ACTIVE_TASK_FAST_PATH_CLARIFY",
                "CONTINUATION-12": "APPROVAL_REJECT_NO_WRITE",
                "POLICY_PERMISSION-07": "DELETE_ONLY_PROHIBITION",
            },
        }
        output = args.dataset.with_suffix(".freeze.json")
        output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("FROZEN:", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
