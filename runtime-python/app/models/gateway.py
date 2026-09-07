import asyncio
from collections.abc import Callable
from typing import Any
from app.models.contracts import ModelProvider, ModelRequest, ModelResponse
from app.models.errors import ModelError, ModelErrorType
from app.models.providers import normalize_provider_error

ModelEventHandler = Callable[[dict[str, Any]], None]

class ModelGateway:
    def __init__(self, provider: ModelProvider, *, timeout: float, max_retries: int) -> None:
        self.provider, self.timeout, self.max_retries = provider, timeout, max(0, max_retries)

    async def generate(self, request: ModelRequest, on_event: ModelEventHandler | None = None) -> ModelResponse:
        timeout = request.timeout or self.timeout
        self._emit(on_event, "model_call_started", provider=self.provider.name, model=request.model)
        for attempt in range(self.max_retries + 1):
            try:
                response = await asyncio.wait_for(self.provider.generate(request), timeout=timeout)
                self._emit(on_event, "model_call_completed", provider=response.provider, model=response.model,
                    latency_ms=response.latency_ms, input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens, total_tokens=response.total_tokens,
                    estimated_cost=response.estimated_cost or 0.0,
                    cost_known=response.estimated_cost is not None, attempts=attempt + 1)
                return response
            except asyncio.TimeoutError:
                error = ModelError(ModelErrorType.TIMEOUT, f"model call timed out after {timeout}s", retryable=True)
            except ModelError as exc:
                error = exc
            except Exception as exc:
                error = normalize_provider_error(exc)
            will_retry = error.retryable and attempt < self.max_retries
            kind = "model_call_retry" if will_retry else "model_call_failed"
            self._emit(on_event, kind, provider=self.provider.name, model=request.model,
                error_type=error.error_type.value, attempt=attempt + 1,
                max_retries=self.max_retries, retrying=will_retry)
            if not will_retry: raise error
            await asyncio.sleep(min(0.25 * (2**attempt), 1.0))
        raise AssertionError("unreachable")

    @staticmethod
    def _emit(handler: ModelEventHandler | None, kind: str, **detail: Any) -> None:
        if handler is not None: handler({"kind": kind, **detail})
