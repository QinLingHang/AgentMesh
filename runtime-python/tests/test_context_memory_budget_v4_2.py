from app.memory import MemoryMessage
from app.services.context_builder import build_agent_context


def test_conversation_memory_is_recent_first_and_bounded():
    messages = [
        MemoryMessage(role="user" if i % 2 == 0 else "assistant", content=(f"turn-{i}-" + "x" * 1800))
        for i in range(12)
    ]

    context = build_agent_context(
        task="follow up",
        memory_messages=messages,
        retrieval_hits=[],
    )

    memory_section = context.split("[Conversation Memory]\n", 1)[1]
    # No single message may replay an entire large prior answer, and the total
    # conversation section remains near the 6k budget (small role-label slack).
    assert "turn-0-" not in memory_section
    assert "turn-11-" in memory_section
    before_next_section = memory_section.split("\n\n[", 1)[0]
    assert len(before_next_section) < 6500
