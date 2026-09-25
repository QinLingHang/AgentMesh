from __future__ import annotations

from typing import Sequence, Any


def recent_conversation_context_allows_stream(
    memory_messages: Sequence[Any], history_source: str,
) -> bool:
    """Return whether ordinary recent chat context may use native token streaming.

    Go-supplied recent conversation rows are already-visible, bounded chat
    context. They are not recalled long-term/private Memory. Long-term memory,
    conversation capsules, RAG evidence and other guarded sources are checked
    separately by the Runtime before enabling a stream.
    """
    return not memory_messages or history_source == "control_plane_history"
