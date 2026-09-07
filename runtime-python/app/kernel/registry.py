from .base import AgentMeshPlugin
from .context import RuntimeContext

class PluginRegistry:
    def __init__(self, context: RuntimeContext) -> None:
        self.context = context
        self._plugins: dict[str, AgentMeshPlugin] = {}

    def register(self, plugin: AgentMeshPlugin) -> None:
        if plugin.manifest.id in self._plugins:
            raise RuntimeError(f"duplicate plugin: {plugin.manifest.id}")
        self._plugins[plugin.manifest.id] = plugin

    def get(self, plugin_id: str) -> AgentMeshPlugin:
        try:
            return self._plugins[plugin_id]
        except KeyError as exc:
            raise KeyError(f"plugin not found: {plugin_id}") from exc

    async def start_all(self) -> None:
        for plugin in self._plugins.values():
            await plugin.setup(self.context)
            await plugin.start()

    async def stop_all(self) -> None:
        for plugin in reversed(list(self._plugins.values())):
            await plugin.stop()

    def info(self) -> list[dict[str, str]]:
        result = []
        for p in self._plugins.values():
            item = {
                "id": p.manifest.id,
                "name": p.manifest.name,
                "version": p.manifest.version,
                "kind": p.manifest.kind.value,
                "status": p.status.value,
            }
            if hasattr(p, "provider"):
                item["provider"] = str(p.provider)
            if hasattr(p, "model"):
                item["model"] = str(p.model)
            result.append(item)
        return result
