"""Regression: Full Runtime uses genuine provider deltas, never fabricated chunks."""
import asyncio
import pytest

from app.models.contracts import ModelMessage, ModelRequest, ModelResponse
from app.models.gateway import ModelGateway


def _request():
    return ModelRequest(model="test-model", messages=[ModelMessage(role="user", content="hello")])


class NativeProvider:
    name = "openai_compatible"

    def __init__(self):
        self.generate_count = 0
        self.stream_count = 0

    async def generate(self, request):
        self.generate_count += 1
        raise AssertionError("streaming must not call nonstream generation")

    async def stream(self, request):
        self.stream_count += 1
        yield {"type": "delta", "delta": "真"}
        yield {"type": "delta", "delta": "流式"}
        yield {"type": "done", "content": "真流式", "model": request.model,
               "provider": self.name, "input_tokens": 2, "output_tokens": 3,
               "total_tokens": 5, "latency_ms": 4, "estimated_cost": 0.02}


def test_real_provider_deltas_and_final_match():
    async def go():
        provider = NativeProvider()
        gateway = ModelGateway(provider, timeout=10, max_retries=3)
        deltas, events = [], []
        result = await gateway.generate_stream(_request(), events.append, deltas.append)
        assert deltas == ["真", "流式"]
        assert result.content == "".join(deltas)
        assert result.estimated_cost == 0.02
        assert provider.stream_count == 1 and provider.generate_count == 0
        assert events[-1]["kind"] == "model_call_completed"
    asyncio.run(go())


def test_no_second_attempt_after_stream_error():
    class BrokenNative(NativeProvider):
        async def stream(self, request):
            self.stream_count += 1
            yield {"type": "delta", "delta": "visible"}
            raise ConnectionError("stream interrupted")

    async def go():
        provider = BrokenNative()
        gateway = ModelGateway(provider, timeout=10, max_retries=5)
        deltas = []
        with pytest.raises(ConnectionError, match="interrupted"):
            await gateway.generate_stream(_request(), on_delta=deltas.append)
        assert deltas == ["visible"]
        assert provider.stream_count == 1 and provider.generate_count == 0
    asyncio.run(go())


def test_mock_must_not_fake_token_stream():
    class Mock:
        name = "mock"
        stream_count = 0
        async def generate(self, request):
            return ModelResponse(content="complete", provider="mock", model=request.model)
        async def stream(self, request):
            self.stream_count += 1
            yield {"type": "delta", "delta": "fake"}
    async def go():
        provider = Mock()
        deltas = []
        result = await ModelGateway(provider, timeout=10, max_retries=0).generate_stream(
            _request(), on_delta=deltas.append,
        )
        assert result.content == "complete" and deltas == [] and provider.stream_count == 0
    asyncio.run(go())


def test_mismatched_final_stream_is_not_accepted():
    class Mismatch(NativeProvider):
        async def stream(self, request):
            yield {"type": "delta", "delta": "hello"}
            yield {"type": "done", "content": "different"}
    async def go():
        with pytest.raises(RuntimeError, match="did not match"):
            await ModelGateway(Mismatch(), timeout=10, max_retries=0).generate_stream(_request())
    asyncio.run(go())


def test_recent_control_plane_chat_history_does_not_disable_native_runtime_streaming():
    from app.runtime_streaming_policy import recent_conversation_context_allows_stream
    history = [object(), object()]
    assert recent_conversation_context_allows_stream(history, 'control_plane_history')
    assert not recent_conversation_context_allows_stream(history, 'runtime_memory')
    assert recent_conversation_context_allows_stream([], 'runtime_memory')


def test_same_turn_automatic_memory_write_does_not_disable_runtime_native_streaming():
    """Regression for Interview Release: Memory writer always returns an outcome.

    A completed/skipped automatic write is an auxiliary side effect based only on
    direct user text. It is not injected into the same answer and same-turn
    re-retrieval is forbidden, so it must not be a native-streaming blocker.
    """
    from pathlib import Path

    engine_source = (
        Path(__file__).resolve().parents[1] / "app" / "services" / "engine.py"
    ).read_text(encoding="utf-8")
    assert "and memory_write_outcome is None" not in engine_source
    assert "Same-turn automatic Memory writes" in engine_source or "Automatic same-turn Memory write" in engine_source

def test_agentmesh_topic_name_never_disables_native_runtime_streaming():
    """Streaming eligibility must depend on evidence/state, never topic words."""
    from pathlib import Path

    engine_source = (
        Path(__file__).resolve().parents[1] / "app" / "services" / "engine.py"
    ).read_text(encoding="utf-8")
    assert '"agentmesh" not in req.task.casefold()' not in engine_source


def test_mcp_selection_skip_is_not_counted_as_mcp_activity():
    from pathlib import Path

    engine_source = (
        Path(__file__).resolve().parents[1] / "app" / "services" / "engine.py"
    ).read_text(encoding="utf-8")
    assert '"capability_discovery",\n                "MCP Selection Skipped"' in engine_source
    assert '"mcp",\n                "MCP Discovery Skipped"' not in engine_source

