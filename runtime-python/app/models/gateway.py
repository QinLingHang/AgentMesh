import asyncio
from collections.abc import Callable
from collections.abc import AsyncIterator
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

    async def stream(
        self,
        request: ModelRequest,
        on_event: ModelEventHandler | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream provider deltas while preserving the Gateway boundary.

        Streaming calls intentionally do not retry after the first frame: a
        replay would duplicate already-visible output. Providers that do not
        expose ``stream`` are adapted to one generated response so custom test
        providers retain the same contract.
        """

        timeout = request.timeout or self.timeout
        self._emit(
            on_event,
            "model_stream_started",
            provider=self.provider.name,
            model=request.model,
        )

        stream_method = getattr(self.provider, "stream", None)
        if not callable(stream_method):
            response = await self.generate(request, on_event)
            if response.content:
                delta = {"type": "delta", "delta": response.content}
                self._emit(on_event, "model_stream_delta", **delta)
                yield delta
            done = {
                "type": "done",
                "content": response.content,
                "provider": response.provider,
                "model": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "total_tokens": response.total_tokens,
                "latency_ms": response.latency_ms,
                "finish_reason": response.finish_reason,
                "estimated_cost": response.estimated_cost,
                "tool_calls": [
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": dict(call.arguments),
                    }
                    for call in response.tool_calls
                ],
            }
            self._emit(on_event, "model_stream_completed", **done)
            yield done
            return

        started = asyncio.get_running_loop().time()
        chunks: list[str] = []
        completed = False
        try:
            async with asyncio.timeout(timeout):
                async for item in stream_method(request):
                    if not isinstance(item, dict):
                        item = {"type": "delta", "delta": str(item)}
                    else:
                        item = dict(item)
                    if item.get("type") == "delta" and item.get("delta"):
                        chunks.append(str(item["delta"]))
                    self._emit(on_event, "model_stream_delta", **item)
                    yield item
                    if item.get("type") == "done":
                        completed = True
                        self._emit(on_event, "model_stream_completed", **item)
                        return
        except asyncio.TimeoutError as exc:
            error = ModelError(
                ModelErrorType.TIMEOUT,
                f"model stream timed out after {timeout}s",
                retryable=False,
            )
            self._emit(
                on_event,
                "model_stream_failed",
                provider=self.provider.name,
                model=request.model,
                error_type=error.error_type.value,
            )
            raise error from exc
        except asyncio.CancelledError:
            self._emit(
                on_event,
                "model_stream_cancelled",
                provider=self.provider.name,
                model=request.model,
            )
            raise
        except ModelError as exc:
            self._emit(
                on_event,
                "model_stream_failed",
                provider=self.provider.name,
                model=request.model,
                error_type=exc.error_type.value,
            )
            raise
        except Exception as exc:
            error = normalize_provider_error(exc)
            self._emit(
                on_event,
                "model_stream_failed",
                provider=self.provider.name,
                model=request.model,
                error_type=error.error_type.value,
            )
            raise error from exc

        if not completed:
            done = {
                "type": "done",
                "content": "".join(chunks),
                "provider": self.provider.name,
                "model": request.model,
                "latency_ms": int((asyncio.get_running_loop().time() - started) * 1000),
            }
            self._emit(on_event, "model_stream_completed", **done)
            yield done

    @staticmethod
    def _emit(handler: ModelEventHandler | None, kind: str, **detail: Any) -> None:
        if handler is not None: handler({"kind": kind, **detail})
