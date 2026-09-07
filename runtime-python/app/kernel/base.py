from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import RuntimeContext

class PluginKind(str, Enum):
    MODEL = "model"
    AGENT = "agent"
    SCHEDULER = "scheduler"

class PluginStatus(str, Enum):
    REGISTERED = "registered"
    READY = "ready"
    STOPPED = "stopped"

@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    kind: PluginKind

class AgentMeshPlugin(ABC):
    manifest: PluginManifest
    status: PluginStatus = PluginStatus.REGISTERED

    @abstractmethod
    async def setup(self, context: "RuntimeContext") -> None:
        ...

    async def start(self) -> None:
        self.status = PluginStatus.READY

    async def stop(self) -> None:
        self.status = PluginStatus.STOPPED
