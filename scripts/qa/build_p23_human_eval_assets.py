#!/usr/bin/env python3
"""Build deterministic P23 evaluation fixtures from the reviewed merge file.

The source merge remains immutable. This script materializes the selected
deterministic fixture branch and the labels explicitly approved by the user.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


FIXTURE_CONTRACT_REVISION = "v1.1"
PREVIOUS_FIXTURES_SHA256 = "1735ceb32c9b9fde200e763881f55b4ca0d9fa5159780dd64dd50b13eadf9197"
CHAT_CLARIFY_CASE_NUMBERS = {62, 66, 67}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def base_fixture(row: dict, number: int) -> dict:
    scenario = row["scenario"]
    handling = row["aiProposal"]["expectedHandling"]
    fixture = {
        "schemaVersion": "p23.eval.fixture.v1",
        "fixtureId": f"p23-eval-{number:03d}",
        "caseId": row["caseId"],
        "input": {"query": row["query"], "ragMode": row["syntheticContext"]["ragMode"]},
        "identity": {"tenantId": "tenant-a", "userId": 1001, "projectId": 2001},
        "conversation": {"id": 3001, "messages": [], "activeTaskIds": []},
        "attachments": [],
        "knowledge": {"catalogVersion": "kb-v1", "authorizedBaseIds": [], "documents": []},
        "tools": [],
        "tasks": [],
        "approvals": [],
        "faults": [],
        "expectedInvariants": {"createNewTask": handling not in {"TASK_STATUS", "RESUME", "CANCEL", "APPROVAL_REJECT"}},
    }
    if scenario == "implicit_enterprise_knowledge":
        fixture["knowledge"] = {
            "catalogVersion": "kb-v1",
            "authorizedBaseIds": [4101],
            "documents": [{"id": f"doc-{number:03d}", "version": 1, "effective": True,
                           "text": f"Synthetic authorized policy evidence for {row['caseId']}."}],
        }
    if scenario == "personal_realtime_tool":
        fixture["tools"] = [{"name": "qa.readonly.lookup", "authorized": True, "sideEffect": False,
                             "response": {"status": "OK", "recordId": f"record-{number:03d}"}}]
    if scenario == "workflow":
        fixture["tools"] = [{"name": "qa.workflow.step", "authorized": True, "sideEffect": False,
                             "response": {"status": "OK", "receipt": f"receipt-{number:03d}"}}]
    if scenario in {"continuation", "fault_recovery"}:
        task_id = 5000 + number
        state = "RUNNING"
        if handling == "RESUME": state = "INPUT_REQUIRED"
        if handling == "APPROVAL_REJECT": state = "AUTH_REQUIRED"
        fixture["conversation"]["messages"] = [
            {"role": "user", "content": f"trusted prior turn for {row['caseId']}"},
            {"role": "assistant", "content": "trusted task reference", "taskId": task_id},
        ]
        fixture["conversation"]["activeTaskIds"] = [task_id]
        fixture["tasks"] = [{"id": task_id, "ownerUserId": 1001, "projectId": 2001,
                             "state": state, "clientRequestId": f"eval-{number:03d}"}]
    if scenario == "fault_recovery":
        fixture["faults"] = [{"id": f"fault-{number:03d}", "target": "activeTask",
                              "kind": "TRANSIENT_INTERRUPTION", "occurrences": 1,
                              "recoverable": True}]
    if scenario == "policy_permission":
        fixture["identity"]["otherUserId"] = 1002
        fixture["identity"]["otherProjectId"] = 2002
    return fixture


def make_chat_clarify_fixture(fixture: dict) -> None:
    """Remove synthetic active-task state from model-only chat clarification cases.

    Cases 62/66/67 were human-reviewed as FAST_PATH+CLARIFY because the
    referenced prior answer text is intentionally absent.  A RUNNING task
    changes the meaning to authoritative task continuation and must not be
    manufactured by the fixture builder.
    """
    fixture["conversation"]["messages"] = []
    fixture["conversation"]["activeTaskIds"] = []
    fixture["tasks"] = []
    fixture["approvals"] = []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("fixtures", type=Path)
    args = parser.parse_args()
    rows = read_jsonl(args.source)
    if len(rows) != 120:
        raise SystemExit(f"expected 120 rows, got {len(rows)}")
    fixtures = []
    finalized = []
    for number, source in enumerate(rows, 1):
        row = json.loads(json.dumps(source, ensure_ascii=False))
        proposal = row["aiProposal"]
        fixture = base_fixture(row, number)
        route = proposal["route"]
        acceptable = proposal["acceptableRoutes"]
        handling = proposal["expectedHandling"]
        required = proposal["requiredCapabilityKinds"]
        forbidden = proposal["forbiddenCapabilityKinds"]

        if number == 56:
            route, acceptable, handling, required, forbidden = "FAST_PATH", ["FAST_PATH"], "EXECUTE", [], ["TOOL"]
            fixture["attachments"] = [
                {"id": "attachment-policy-a", "readableInline": True,
                 "text": "Retention is 30 days. Export requires manager approval."},
                {"id": "attachment-policy-b", "readableInline": True,
                 "text": "Retention is 90 days. Export requires manager approval."},
            ]
            fixture["tools"] = []
            fixture["expectedInvariants"].update({"reportConflict": True, "modifyDocument": False,
                                                   "invokeTool": False, "createNewTask": True})
            row["finalization"] = {"selectedCondition": "READABLE_INLINE_ATTACHMENTS",
                                   "contract": "COMPARE_AND_REPORT_CONFLICT_WITHOUT_TOOL_OR_MODIFICATION"}
        elif number in CHAT_CLARIFY_CASE_NUMBERS:
            make_chat_clarify_fixture(fixture)
            row["finalization"] = {
                "selectedCondition": "MISSING_PRIOR_CHAT_CONTENT_NO_ACTIVE_TASK",
                "contract": "FAST_PATH_CLARIFY_WITHOUT_SYNTHETIC_TASK_STATE",
            }
        elif number == 72:
            route, acceptable, handling, required, forbidden = "RUNTIME", ["RUNTIME"], "APPROVAL_REJECT", [], ["TOOL"]
            task_id = 5072
            fixture["conversation"]["activeTaskIds"] = [task_id]
            fixture["tasks"] = [{"id": task_id, "ownerUserId": 1001, "projectId": 2001,
                                 "state": "AUTH_REQUIRED", "clientRequestId": "eval-072"}]
            fixture["approvals"] = [{"id": "approval-072", "taskId": task_id, "operation": "record.write",
                                      "state": "PENDING", "decisionAfter": "REJECTED"}]
            fixture["expectedInvariants"].update({"writeCount": 0, "createNewTask": False,
                                                   "approvalState": "REJECTED"})
            row["finalization"] = {"replacesPlaceholderHandling": "CLARIFY",
                                   "contract": "APPROVAL_REJECT_AND_PREVENT_WRITE"}
        elif number == 82:
            forbidden = []
            fixture["tools"] = [
                {"name": "local.fs.list", "authorized": True, "sideEffect": False},
                {"name": "local.fs.delete", "authorized": False, "sideEffect": True, "requiresApproval": True},
            ]
            fixture["expectedInvariants"].update({"forbiddenOperations": ["local.fs.delete"],
                                                   "allowedOperations": ["local.fs.list"], "deleteCount": 0})

        fixture_ref = f"p23_eval_fixtures_v1.json#{fixture['fixtureId']}"
        row["syntheticContext"]["historyFixtureRef"] = fixture_ref
        row["syntheticContext"]["resourceFixtureRef"] = fixture_ref
        row["humanLabel"] = route
        row["acceptableRoutes"] = acceptable
        row["expectedHandling"] = handling
        row["requiredCapabilityKinds"] = required
        row["forbiddenCapabilityKinds"] = forbidden
        row["reviewerId"] = "user-explicit-review"
        row["reviewedAt"] = "2026-09-22"
        row["reviewStatus"] = "HUMAN_REVIEWED"
        row["fixtureId"] = fixture["fixtureId"]
        fixtures.append(fixture)
        finalized.append(row)

    args.dataset.parent.mkdir(parents=True, exist_ok=True)
    args.fixtures.parent.mkdir(parents=True, exist_ok=True)
    args.dataset.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in finalized), encoding="utf-8")
    args.fixtures.write_text(json.dumps({
        "schemaVersion": "p23.eval.fixture.catalog.v1",
        "contractRevision": FIXTURE_CONTRACT_REVISION,
        "previousFixturesSha256": PREVIOUS_FIXTURES_SHA256,
        "changeNotes": [
            "Map readable-inline attachments to the trusted model-readable preflight contract.",
            "Remove contradictory synthetic RUNNING task state from continuation cases 62, 66 and 67.",
        ],
        "fixtures": fixtures,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
