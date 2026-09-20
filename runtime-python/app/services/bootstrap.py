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

    await registry.start_all()

    return registry