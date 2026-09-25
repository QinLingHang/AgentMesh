"""Go-generated Full Runtime JSON must pass Python's real Pydantic request schema.

The fixture is emitted by encoding runtime.ExecuteRequest with encoding/json,
not a hand-written Python approximation of the Go field names.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import RuntimeRequest


_FIXTURE = Path(__file__).parent / "fixtures" / "go_full_runtime_desktop.json"


def _go_desktop_request():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_go_full_runtime_nonproject_desktop_payload_passes_pydantic():
    parsed = RuntimeRequest.model_validate(_go_desktop_request())
    assert parsed.effective_rag_policy.allowed_scopes == []
    assert parsed.rag_policy.scopes == []
    assert parsed.tools[0].name == "local.fs.list"


def test_go_full_runtime_null_scopes_is_rejected_not_silently_authorized():
    payload = _go_desktop_request()
    payload["effectiveRagPolicy"]["allowedScopes"] = None
    with pytest.raises(ValidationError) as exc:
        RuntimeRequest.model_validate(payload)
    assert any(
        error["loc"] == ("effectiveRagPolicy", "allowedScopes") and error["type"] == "list_type"
        for error in exc.value.errors()
    )
