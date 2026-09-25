import asyncio
import pytest
from app.models import ModelError, ModelErrorType, ModelGateway, ModelMessage, ModelRequest, ModelResponse
from app.models.providers import MockModelProvider

def request(timeout=None):
    return ModelRequest(model="test-model", messages=[ModelMessage(role="user", content="hello")], timeout=timeout)

@pytest.mark.asyncio
async def test_mock_provider_returns_normalized_response():
    response = await MockModelProvider().generate(request())
    assert response.content and response.provider == "mock" and response.model == "test-model"
    assert response.total_tokens == response.input_tokens + response.output_tokens
    assert response.latency_ms >= 0 and response.finish_reason == "stop" and response.estimated_cost == 0

class FakeProvider:
    name = "fake"
    def __init__(self, errors=None):
        self.errors, self.calls = list(errors or []), 0
    async def generate(self, req):
        self.calls += 1
        if self.errors: raise self.errors.pop(0)
        return ModelResponse(content="ok", provider=self.name, model=req.model, latency_ms=3)

@pytest.mark.asyncio
async def test_gateway_calls_provider_and_emits_events():
    provider, events = FakeProvider(), []
    response = await ModelGateway(provider, timeout=1, max_retries=2).generate(request(), events.append)
    assert response.content == "ok" and provider.calls == 1
    assert [event["kind"] for event in events] == ["model_call_started", "model_call_completed"]

@pytest.mark.asyncio
async def test_retry_stays_within_configured_limit(monkeypatch):
    provider, events = FakeProvider([ModelError(ModelErrorType.UNAVAILABLE, "down", retryable=True)] * 3), []
    async def no_sleep(_): pass
    monkeypatch.setattr("app.models.gateway.asyncio.sleep", no_sleep)
    with pytest.raises(ModelError) as raised:
        await ModelGateway(provider, timeout=1, max_retries=2).generate(request(), events.append)
    assert raised.value.error_type == ModelErrorType.UNAVAILABLE and provider.calls == 3
    assert sum(event["kind"] == "model_call_retry" for event in events) == 2

@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [ModelErrorType.AUTH, ModelErrorType.BAD_REQUEST])
async def test_non_retryable_errors_are_not_retried(error_type):
    provider = FakeProvider([ModelError(error_type, "invalid", retryable=False)])
    with pytest.raises(ModelError) as raised:
        await ModelGateway(provider, timeout=1, max_retries=2).generate(request())
    assert raised.value.error_type == error_type and provider.calls == 1

@pytest.mark.asyncio
async def test_timeout_is_normalized_and_bounded():
    class SlowProvider:
        name = "slow"
        calls = 0
        async def generate(self, req):
            self.calls += 1
            await asyncio.sleep(1)
    provider = SlowProvider()
    with pytest.raises(ModelError) as raised:
        await ModelGateway(provider, timeout=0.001, max_retries=0).generate(request())
    assert raised.value.error_type == ModelErrorType.TIMEOUT and provider.calls == 1

class StreamingProvider:
    name = "streaming-fake"

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = 0

    async def stream(self, req):
        self.calls += 1
        script = self.scripts[min(self.calls - 1, len(self.scripts) - 1)]
        parts = []
        for delay, text in script:
            await asyncio.sleep(delay)
            if text is None:
                continue
            parts.append(text)
            yield {"type": "delta", "delta": text}
        content = "".join(parts)
        yield {
            "type": "done",
            "content": content,
            "provider": self.name,
            "model": req.model,
            "input_tokens": 1,
            "output_tokens": max(1, len(content)),
            "total_tokens": 1 + max(1, len(content)),
            "latency_ms": 1,
            "finish_reason": "stop",
        }


@pytest.mark.asyncio
async def test_stream_timeout_is_progress_idle_deadline_not_whole_response_deadline():
    # Keep each progress gap comfortably below the idle deadline while
    # making the total response duration exceed it.  The larger margins
    # avoid Windows event-loop/timer-granularity flakes.
    provider = StreamingProvider([
        [(0.05, "a"), (0.05, "b"), (0.05, "c"), (0.05, "d")],
    ])
    gateway = ModelGateway(provider, timeout=0.15, max_retries=0)
    response = await gateway.generate_stream(request())
    assert response.content == "abcd"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_stream_retries_only_before_first_delta_on_progress_timeout():
    provider = StreamingProvider([
        [(0.25, "late")],
        [(0.02, "ok")],
    ])
    events = []

    gateway = ModelGateway(provider, timeout=0.10, max_retries=1)
    response = await gateway.generate_stream(request(), events.append)
    assert response.content == "ok"
    assert provider.calls == 2
    assert any(event["kind"] == "model_call_retry" for event in events)


@pytest.mark.asyncio
async def test_stream_does_not_retry_after_real_delta_then_idle_timeout():
    provider = StreamingProvider([
        [(0.02, "first"), (0.25, "late")],
        [(0.02, "must-not-run")],
    ])
    events = []

    gateway = ModelGateway(provider, timeout=0.10, max_retries=2)
    with pytest.raises(ModelError) as raised:
        await gateway.generate_stream(request(), events.append)
    assert raised.value.error_type == ModelErrorType.TIMEOUT
    assert provider.calls == 1
    assert not any(event["kind"] == "model_call_retry" for event in events)
