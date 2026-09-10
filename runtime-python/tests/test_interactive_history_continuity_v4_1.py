from app.schemas import InteractiveMessage, InteractiveStreamRequest
from app.services.interactive_stream import _bounded_history, _SYSTEM_PROMPT


def test_interactive_history_keeps_recent_turn_and_continuity_instruction():
    req = InteractiveStreamRequest(
        user_id=7,
        request_id="fast-continuity",
        conversationId=86,
        task="展开讲讲",
        history=[
            InteractiveMessage(role="user", content="Python 和 Java 有什么区别？"),
            InteractiveMessage(role="assistant", content="这是一个更早的话题。"),
            InteractiveMessage(role="user", content="最大子数组和没思路，应该怎么想？"),
            InteractiveMessage(role="assistant", content="先从暴力枚举开始观察重复计算。"),
        ],
    )

    history = _bounded_history(req)
    assert history[-2].content.startswith("最大子数组和")
    assert history[-1].content.startswith("先从暴力枚举")
    assert "优先承接最近一轮" in _SYSTEM_PROMPT

def test_interactive_history_preserves_tail_of_long_assistant_option_prompt():
    long_answer = (
        "最大子数组和讲解。" + "中间推导" * 500 +
        "\n如果你想继续：1. 用 Python 跑一遍；2. 画状态转移；3. 换数组练习。"
    )
    req = InteractiveStreamRequest(
        user_id=7,
        request_id="fast-option-tail",
        conversationId=86,
        task="1",
        history=[
            InteractiveMessage(role="user", content="最大子数组和没思路，应该怎么想？"),
            InteractiveMessage(role="assistant", content=long_answer),
        ],
    )

    history = _bounded_history(req)
    assert "1. 用 Python 跑一遍" in history[-1].content
    assert "3. 换数组练习" in history[-1].content
    assert "1/2/3/A/B" in _SYSTEM_PROMPT

