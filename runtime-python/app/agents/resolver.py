from app.agents.contracts import (
    AgentExecutor,
)
from app.kernel import (
    PluginRegistry,
)
from app.schemas import (
    AgentProfile,
)


class AgentExecutorResolutionError(
    RuntimeError,
):
    """Raised when an agent protocol cannot be resolved to an executor."""


class AgentExecutorResolver:
    """Routes an agent to its executor by protocol + executorType.

    Routing matrix (P37 OpenJiuwen adapter plan):

        protocol  executorType      executor
        --------  ----------------  -----------------------------
        internal  native / empty    existing agent.internal
        internal  openjiuwen        agent.openjiuwen (new adapter)
        http      native / empty    agent.http
        a2a       native / empty    agent.a2a
        langgraph native / empty    agent.langgraph
        !=internal openjiuwen       configuration error (explicit)
    """

    def __init__(
        self,
        registry: PluginRegistry,
    ) -> None:
        self._registry = registry

    def resolve(
        self,
        agent: AgentProfile | str,
    ) -> AgentExecutor:
        if isinstance(
            agent,
            AgentProfile,
        ):
            protocol = agent.protocol

            executor_type = (
                agent.executor_type
                or "native"
            )

        else:
            # Backward compatibility: legacy call sites and tests may
            # pass a bare protocol string.
            protocol = agent

            executor_type = "native"

        normalized_protocol = protocol.strip().lower()

        normalized_executor = executor_type.strip().lower() or "native"

        if not normalized_protocol:
            raise AgentExecutorResolutionError(
                "agent protocol must not be empty",
            )

        if normalized_executor not in {
            "native",
            "openjiuwen",
        }:
            raise AgentExecutorResolutionError(
                (
                    "unsupported agent executor type: "
                    f"{normalized_executor}"
                ),
            )

        if (
            normalized_executor
            == "openjiuwen"
            and normalized_protocol
            != "internal"
        ):
            raise AgentExecutorResolutionError(
                (
                    "executorType 'openjiuwen' is only supported "
                    f"with protocol 'internal', got '{normalized_protocol}'"
                ),
            )

        # Route by protocol + executorType: openjiuwen agents on the
        # internal boundary go to the OpenJiuwen adapter, everything
        # else keeps the protocol-keyed executor.
        if normalized_executor == "openjiuwen":
            plugin_id = "agent.openjiuwen"

        else:
            plugin_id = f"agent.{normalized_protocol}"

        try:
            executor = self._registry.get(
                plugin_id,
            )

        except KeyError as exc:
            raise AgentExecutorResolutionError(
                (
                    "unsupported agent protocol: "
                    f"{normalized_protocol}"
                ),
            ) from exc

        if not isinstance(
            executor,
            AgentExecutor,
        ):
            raise AgentExecutorResolutionError(
                (
                    f"plugin {plugin_id} does not "
                    "implement AgentExecutor"
                ),
            )

        return executor
