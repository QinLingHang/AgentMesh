from app.agents.contracts import AgentExecutor
from app.kernel import PluginRegistry


class AgentExecutorResolutionError(RuntimeError):
    """Raised when an agent protocol cannot be resolved to an executor."""


class AgentExecutorResolver:
    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    def resolve(self, protocol: str) -> AgentExecutor:
        normalized_protocol = protocol.strip().lower()

        if not normalized_protocol:
            raise AgentExecutorResolutionError(
                "agent protocol must not be empty"
            )

        plugin_id = f"agent.{normalized_protocol}"

        try:
            executor = self._registry.get(plugin_id)
        except KeyError as exc:
            raise AgentExecutorResolutionError(
                f"unsupported agent protocol: {normalized_protocol}"
            ) from exc

        if not isinstance(executor, AgentExecutor):
            raise AgentExecutorResolutionError(
                f"plugin {plugin_id} does not implement AgentExecutor"
            )

        return executor