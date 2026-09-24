"""Knowledge Runtime: real Context Builder is reused at the FINAL model call, offline."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = Path(__file__).resolve().parent / "fixtures/generate-synthesis-context.py"


def fixture(kind):
    result = subprocess.run(
        [sys.executable, str(GENERATOR), kind],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("kind", ["GLOBAL", "PROJECT"])
def test_real_provenance_reaches_final_synthesis_and_bad_citations_fail(kind):
    result = fixture(kind)
    prompt = result["prompt"]
    assert "[Current Task]" in prompt
    assert prompt.count("\n[Retrieved Knowledge]\n") == 1
    assert prompt.count("\n[Citation Policy]\n") == 1
    assert "[Evidence 2]\n" in prompt
    assert result["marker"] in prompt
    assert "available_citations=[1] [2]" in prompt
    assert result["validCitation"]
    assert result["wrongCitationRejected"]
    assert result["missingCitationRejected"]
    assert result["evidenceGate"] == {
        "normal": 2, "off": 0, "explicitOff": 0, "memoryOverview": 0,
        "blocked": 0, "noInjection": 0, "lateRequired": 2, "empty": 0,
    }
    # Stale Agent output is never promoted into a top-level evidence section.
    assert "\n> [Retrieved Knowledge]\n" in prompt
    assert "\n> [Evidence 77]\n" in prompt


@pytest.mark.parametrize("kind", ["GLOBAL", "PROJECT"])
def test_zero_evidence_cannot_be_invented_from_previous_agent_output(kind):
    result = fixture(kind)
    prompt = result["zeroPrompt"]
    assert "\n[Retrieved Knowledge]\n" not in prompt
    assert "\n[Citation Policy]\n" not in prompt
    assert "\n> [Retrieved Knowledge]\n" in prompt
    # The old marker is present ONLY as quoted, untrusted Agent output.
    assert result["marker"] in prompt


def test_engine_final_synthesis_calls_request_local_builder_and_preserves_guard():
    tree = ast.parse((ROOT / "app/services/engine.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    builder_calls = [node for node in calls if isinstance(node.func, ast.Name)
                     and node.func.id == "build_synthesis_context"]
    assert len(builder_calls) == 1
    fields = {item.arg: item.value for item in builder_calls[0].keywords}
    assert isinstance(fields["retrieval_hits"], ast.Name)
    assert fields["retrieval_hits"].id == "synthesis_hits"
    assert any(isinstance(node.func, ast.Name) and node.func.id == "select_synthesis_evidence"
               for node in calls)
    assert isinstance(fields["task"], ast.Attribute) and fields["task"].attr == "task"
    assert any(isinstance(node.func, ast.Name) and node.func.id == "guard_answer_citations"
               for node in calls)
