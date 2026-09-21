import logging

from app.kernel import (
    PluginRegistry,
    RuntimeContext,
)
from app.plugins import (
    AdaptiveSchedulerPlugin,
    CapabilitySchedulerPlugin,
    FixedSchedulerPlugin,
    GreedySchedulerPlugin,
    HTTPAgentPlugin,
    InternalAgentPlugin,
    LangGraphAgentPlugin,
    OpenJiuwenAgentPlugin,
    create_model_plugins,
    A2AAgentPlugin,
)


logger = logging.getLogger(__name__)


async def _stop_registry_after_start_failure(registry: PluginRegistry) -> None:
    """Best-effort cleanup when a plugin fails during registry startup."""

    try:
        await registry.stop_all()
    except BaseException:
        # Preserve the original startup exception. Individual plugin cleanup
        # errors must still be visible in the runtime log.
        logger.exception("Failed to clean up plugins after startup failure")


async def create_registry() -> PluginRegistry:
    context = RuntimeContext()

    registry = PluginRegistry(
        context
    )

    for model_plugin in create_model_plugins():
        registry.register(model_plugin)

    registry.register(
        InternalAgentPlugin()
    )

    registry.register(
        HTTPAgentPlugin()
    )

    registry.register(
        LangGraphAgentPlugin()
    )

    registry.register(
        OpenJiuwenAgentPlugin()
    )

    registry.register(
        FixedSchedulerPlugin()
    )

    registry.register(
        CapabilitySchedulerPlugin()
    )

    registry.register(
        GreedySchedulerPlugin()
    )

    registry.register(
        AdaptiveSchedulerPlugin()
    )

    registry.register(
        A2AAgentPlugin()
    )

    try:
        await registry.start_all()
    except BaseException:
        await _stop_registry_after_start_failure(registry)
        raise

    return registry
