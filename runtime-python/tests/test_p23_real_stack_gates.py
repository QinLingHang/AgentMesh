from __future__ import annotations

import base64

import pytest

from app.schemas import InteractiveStreamRequest, RuntimeAttachment
from app.services.interactive_stream import _safe_document_context
from app.tools.desktop import desktop_tool_definitions
from app.tools.governance import ToolGovernancePolicy


def _attachment(*, ident: int, name: str, text: str) -> RuntimeAttachment:
    raw = text.encode("utf-8")
    return RuntimeAttachment(
        id=ident,
        name=name,
        mediaType="text/plain",
        extension="txt",
        sizeBytes=len(raw),
        contentBase64=base64.b64encode(raw).decode("ascii"),
    )


def test_case56_two_inline_documents_are_both_present_and_no_tool_is_needed():
    req = InteractiveStreamRequest(
        user_id=1,
        request_id="p23-case56",
        conversationId=1,
        task="先比较两份文档，识别冲突，再向我询问后才能修改。",
        attachments=[
            _attachment(
                ident=1,
                name="policy-a.txt",
                text="Retention is 30 days. Export requires manager approval.",
            ),
            _attachment(
                ident=2,
                name="policy-b.txt",
                text="Retention is 90 days. Export requires manager approval.",
            ),
        ],
    )

    document_context, images, notices = _safe_document_context(req)

    assert images == []
    assert [item["status"] for item in notices] == ["ready", "ready"]
    assert "policy-a.txt" in document_context
    assert "Retention is 30 days" in document_context
    assert "policy-b.txt" in document_context
    assert "Retention is 90 days" in document_context
    # The conflict is observable from the exact model input. No Tool call is
    # necessary or authorized merely because two request-local files exist.
    assert "30 days" in document_context and "90 days" in document_context


def test_case56_comparison_fails_closed_when_one_document_is_invalid():
    good = _attachment(ident=1, name="policy-a.txt", text="Retention is 30 days.")
    bad = _attachment(ident=2, name="policy-b.txt", text="Retention is 90 days.")
    bad.content_base64 = "not-base64"
    req = InteractiveStreamRequest(
        user_id=1,
        request_id="p23-case56-invalid",
        conversationId=1,
        task="比较两份文档并识别冲突",
        attachments=[good, bad],
    )

    document_context, images, notices = _safe_document_context(req)
    assert images == []
    assert "30 days" in document_context
    assert any(item["status"] == "error" for item in notices)


def test_case82_read_only_tool_allowed_but_delete_requires_approval():
    tools = {tool.name: tool for tool in desktop_tool_definitions()}
    policy = ToolGovernancePolicy()

    read = policy.evaluate(tools["local.fs.read"])
    delete = policy.evaluate(tools["local.fs.delete"])

    assert read.allowed is True
    assert read.requires_approval is False
    assert delete.allowed is False
    assert delete.requires_approval is True

    approved_delete = policy.evaluate(tools["local.fs.delete"], approved=True)
    assert approved_delete.allowed is True


def test_case82_delete_restriction_does_not_expand_to_neighboring_read_tools():
    tools = {tool.name: tool for tool in desktop_tool_definitions()}
    policy = ToolGovernancePolicy()

    for name in ("local.fs.list", "local.fs.stat", "local.fs.read", "local.fs.search"):
        decision = policy.evaluate(tools[name])
        assert decision.allowed is True, name
        assert decision.requires_approval is False, name

    for name in ("local.fs.delete", "local.fs.move"):
        decision = policy.evaluate(tools[name])
        assert decision.allowed is False, name
        assert decision.requires_approval is True, name
