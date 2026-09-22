from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDependency(str, Enum):
    NONE = "NONE"
    OPTIONAL = "OPTIONAL"
    REQUIRED = "REQUIRED"


class RagPreference(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    ENABLE = "ENABLE"
    DISABLE = "DISABLE"


class TaskSemanticIntent(BaseModel):
    """Shared request-level semantic contract used by discovery/planning.

    This object is deliberately descriptive rather than authoritative: it may
    express what the request appears to need, but it never grants knowledge,
    tool, MCP, or agent permissions. Control-plane policy remains authoritative.
    """

    model_config = ConfigDict(populate_by_name=True)

    objective: str = ""
    intents: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list, alias="requiredCapabilities")
    forbidden_actions: list[str] = Field(default_factory=list, alias="forbiddenActions")
    knowledge_dependency: KnowledgeDependency = Field(
        default=KnowledgeDependency.NONE,
        alias="knowledgeDependency",
    )
    rag_preference: RagPreference = Field(default=RagPreference.UNSPECIFIED, alias="ragPreference")
    requires_tool: bool = Field(default=False, alias="requiresTool")
    requires_external: bool = Field(default=False, alias="requiresExternal")
    requires_memory: bool = Field(default=False, alias="requiresMemory")
    explanation_only: bool = Field(default=False, alias="explanationOnly")
    has_attachments: bool = Field(default=False, alias="hasAttachments")
    mixed_capability_request: bool = Field(default=False, alias="mixedCapabilityRequest")
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)
