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
