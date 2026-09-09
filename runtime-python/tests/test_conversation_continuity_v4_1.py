from app.memory import MemoryMessage
from app.schemas import AgentProfile, InteractiveMessage, RuntimeRequest
from app.services.context_builder import build_agent_context


def _request(history):
    return RuntimeRequest(
        user_id=7,
        request_id="continuity-1",
        conversationId=86,
        task="可以",
        agents=[
            AgentProfile(
                id=1,
                name="General",
                endpoint="internal://general",
                protocol="internal",
                capabilities=["general"],
            )
        ],
        history=history,
    )


def test_runtime_request_accepts_authoritative_cross_path_history():
    req = _request([
        InteractiveMessage(role="user", content="最大子数组和没思路，应该怎么想？"),
        InteractiveMessage(role="assistant", content="先从暴力枚举理解，再观察重复计算。"),
    ])

    assert req.conversation_id == 86
    assert [item.role for item in req.history] == ["user", "assistant"]
    assert "最大子数组和" in req.history[0].content


def test_agent_context_marks_short_followups_as_recent_turn_continuations():
    context = build_agent_context(
        task="可以",
        memory_messages=[
            MemoryMessage(role="user", content="最大子数组和没思路，应该怎么想？"),
            MemoryMessage(role="assistant", content="先从暴力枚举理解，再推导动态规划。"),
        ],
        retrieval_hits=[],
        long_term_memories=[],
    )

    assert "[Conversation Memory]" in context
    assert "最大子数组和" in context
    assert "[Conversation Continuity Policy]" in context
    assert "继续/可以/好的/然后呢/展开" in context
    assert "Prefer the newest user/assistant exchange" in context
