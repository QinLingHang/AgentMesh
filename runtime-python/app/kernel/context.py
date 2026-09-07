from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

EventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]

class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event: str, handler: EventHandler) -> None:
        self._handlers[event].append(handler)

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        for handler in self._handlers.get(event, []):
            result = handler(payload)
            if result is not None and hasattr(result, "__await__"):
                await result

class RuntimeContext:
    def __init__(self) -> None:
        self.services: dict[str, Any] = {}
        self.events = EventBus()

    def provide(self, key: str, service: Any) -> None:
        if key in self.services:
            raise RuntimeError(f"service already registered: {key}")
        self.services[key] = service

    def get(self, key: str) -> Any:
        if key not in self.services:
            raise KeyError(f"service not found: {key}")
        return self.services[key]
