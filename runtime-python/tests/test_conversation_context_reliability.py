from app.schemas import InteractiveMessage, InteractiveStreamRequest, RuntimeRequest
from app.services.interactive_stream import _bounded_history


def _history(count: int) -> list[InteractiveMessage]:
    return [
        InteractiveMessage(
            role="user" if index % 2 == 0 else "assistant",
            content=f"short-turn-{index}",
        )
        for index in range(count)
    ]


def test_interactive_request_accepts_deeper_authoritative_history():
    req = InteractiveStreamRequest(
        user_id=7,
        request_id="conversation-reliability-deep-fast",
        conversationId=99,
        task="继续",
        history=_history(32),
    )
    assert len(req.history) == 32


def test_full_runtime_request_accepts_deeper_authoritative_history():
    req = RuntimeRequest(
        user_id=7,
        request_id="conversation-reliability-deep-full",
        conversationId=99,
        task="继续",
        history=_history(40),
        agents=[],
        tools=[],
        mcpServers=[],
    )
    assert len(req.history) == 40


def test_interactive_context_is_budgeted_but_not_hard_limited_to_eight_rows():
    req = InteractiveStreamRequest(
        user_id=7,
        request_id="conversation-reliability-budget",
        conversationId=99,
        task="继续",
        history=_history(30),
    )
    bounded = _bounded_history(req)
    assert 8 < len(bounded) <= 24
    assert bounded[-1].content == "short-turn-29"
    assert sum(len(item.content) for item in bounded) <= 9000
