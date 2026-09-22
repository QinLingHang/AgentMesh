from app.models import ModelInputAttachment, ModelMessage, ModelRequest
from app.models.providers import _serialize_openai_messages


def test_openai_compatible_transport_uses_structured_text_parts_with_attachment():
    marker = "AGENTMESH_V41_GLOBAL_1234567890"
    request = ModelRequest(
        model="fixture",
        messages=[ModelMessage(role="user", content=f"[Retrieved Knowledge]\n{marker}")],
        attachments=[ModelInputAttachment(
            name="fixture.png",
            media_type="image/png",
            content_base64="AA==",
        )],
    )
    payload = _serialize_openai_messages(request)
    content = payload[0]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": f"[Retrieved Knowledge]\n{marker}"}
    assert content[1]["type"] == "image_url"


def test_openai_compatible_transport_keeps_plain_string_without_attachment():
    request = ModelRequest(
        model="fixture",
        messages=[ModelMessage(role="user", content="plain")],
    )
    payload = _serialize_openai_messages(request)
    assert payload[0]["content"] == "plain"
