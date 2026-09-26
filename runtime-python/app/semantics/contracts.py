from __future__ import annotations

from enum import Enum
from typing import Literal

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
    """Legacy-compatible projection consumed by existing Runtime components.

    P24 makes :class:`ExecutionIntent` authoritative. This projection exists so
    mature Discovery/RAG/Planner code can be reused without creating a second
    semantic engine. Runtime requests carrying ExecutionIntent must derive this
    object from that contract rather than re-analyzing user text.
    """

    model_config = ConfigDict(populate_by_name=True)

    objective: str = ""
    intents: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list, alias="requiredCapabilities")
    forbidden_capabilities: list[str] = Field(default_factory=list, alias="forbiddenCapabilities")
    forbidden_actions: list[str] = Field(default_factory=list, alias="forbiddenActions")
    knowledge_dependency: KnowledgeDependency = Field(default=KnowledgeDependency.NONE, alias="knowledgeDependency")
    rag_preference: RagPreference = Field(default=RagPreference.UNSPECIFIED, alias="ragPreference")
    requires_tool: bool = Field(default=False, alias="requiresTool")
    requires_external: bool = Field(default=False, alias="requiresExternal")
    requires_memory: bool = Field(default=False, alias="requiresMemory")
    explanation_only: bool = Field(default=False, alias="explanationOnly")
    has_attachments: bool = Field(default=False, alias="hasAttachments")
    mixed_capability_request: bool = Field(default=False, alias="mixedCapabilityRequest")
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    is_continuation: bool = Field(default=False, alias="isContinuation")
    trusted_reference_resolvable: bool = Field(default=False, alias="trustedReferenceResolvable")
    side_effect: bool = Field(default=False, alias="sideEffect")
    requested_effects: list[str] = Field(default_factory=list, alias="requestedEffects")
    trusted_history_resolution: Literal["NONE", "REQUIRED", "RESOLVED"] = Field(
        default="NONE", alias="trustedHistoryResolution"
    )


class ContinuationIntent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    is_continuation: bool = Field(default=False, alias="isContinuation")
    relation: Literal[
        "NONE", "EXPLAIN_PREVIOUS", "TRANSFORM_PREVIOUS", "NEW_FACT_FOLLOWUP",
        "REFRESH_DATA", "CONFIRM_ACTION", "RESUME_TASK", "AMBIGUOUS",
    ] = "NONE"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ReferenceIntent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    type: Literal[
        "NONE", "TRUSTED_HISTORY", "CONTEXTUAL_REFERENCE", "REQUEST_INPUT",
        "ATTACHMENT", "EXTERNAL_RESOURCE", "UNRESOLVED",
    ] = "NONE"
    resolvable_from_trusted_history: bool = Field(default=False, alias="resolvableFromTrustedHistory")
    requires_external_resolution: bool = Field(default=False, alias="requiresExternalResolution")
    target_scope: Literal["NONE", "HISTORY", "REQUEST", "ATTACHMENT", "EXTERNAL"] = Field(default="NONE", alias="targetScope")
    trusted_history_resolution: Literal["NONE", "REQUIRED", "RESOLVED"] = Field(
        default="NONE", alias="trustedHistoryResolution"
    )


class ClarificationIntent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    required: bool = False
    reason_code: str = Field(default="", alias="reasonCode", pattern=r"^(?:|[A-Z0-9_]{1,64})$")
    missing_fields: list[Literal[
        "TARGET", "SOURCE", "CONTEXT", "AUTHORIZATION", "PARAMETER", "CAPABILITY"
    ]] = Field(default_factory=list, alias="missingFields", max_length=6)


class ExecutionDependencies(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    knowledge: KnowledgeDependency = KnowledgeDependency.NONE
    memory: bool = False
    fresh_data: bool = Field(default=False, alias="freshData")
    attachment: bool = False
    external_system: bool = Field(default=False, alias="externalSystem")
    tool: bool = False
    mcp: bool = False
    agent: bool = False
    multi_step: bool = Field(default=False, alias="multiStep")
    side_effect: bool = Field(default=False, alias="sideEffect")


class ExecutionCapabilities(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    required_capabilities: list[str] = Field(default_factory=list, alias="requiredCapabilities", max_length=32)
    forbidden_capabilities: list[str] = Field(default_factory=list, alias="forbiddenCapabilities", max_length=32)


class ExecutionIntent(BaseModel):
    """P24 authoritative WHAT contract.

    It contains semantic facts and abstract capability requirements only. It
    deliberately cannot carry Tool/MCP/Agent/Knowledge resource IDs or grant
    permission. Route derives WHERE from it; Discovery resolves WHICH;
    Planner decides HOW; Governance independently decides CAN.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    version: Literal["execution-intent.v1"] = "execution-intent.v1"
    user_intent: str = Field(default="", alias="userIntent", max_length=600)
    task_type: Literal[
        "CHAT", "EXPLAIN", "TRANSFORM", "KNOWLEDGE_QUERY", "OPERATION",
        "MULTI_STEP", "ATTACHMENT_ANALYSIS", "MEMORY_RECALL", "UNKNOWN",
    ] = Field(default="UNKNOWN", alias="taskType")
    continuation: ContinuationIntent = Field(default_factory=ContinuationIntent)
    reference: ReferenceIntent = Field(default_factory=ReferenceIntent)
    clarification: ClarificationIntent = Field(default_factory=ClarificationIntent)
    dependencies: ExecutionDependencies = Field(default_factory=ExecutionDependencies)
    capabilities: ExecutionCapabilities = Field(default_factory=ExecutionCapabilities)
    requested_effects: list[Literal["READ", "WRITE", "EXECUTE", "EXTERNAL_SEND"]] = Field(default_factory=list, alias="requestedEffects", max_length=4)
    forbidden_actions: list[str] = Field(default_factory=list, alias="forbiddenActions", max_length=16)
    rag_preference: RagPreference = Field(default=RagPreference.UNSPECIFIED, alias="ragPreference")
    explanation_only: bool = Field(default=False, alias="explanationOnly")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    semantic_source: Literal["RULE", "MODEL"] = Field(default="RULE", alias="semanticSource")
    reason_codes: list[str] = Field(default_factory=list, alias="reasonCodes", max_length=16)

    def to_task_semantic_intent(self, *, objective: str = "") -> TaskSemanticIntent:
        deps = self.dependencies
        intents: list[str] = []
        if self.task_type in {"EXPLAIN", "TRANSFORM"} or self.explanation_only:
            intents.append("explain")
        if deps.tool or deps.external_system or deps.side_effect:
            intents.append("operate_or_observe")
        if deps.knowledge is not KnowledgeDependency.NONE:
            intents.append("knowledge_grounding")
        if deps.attachment:
            intents.append("attachment_analysis")
        if deps.memory:
            intents.append("memory_recall")
        return TaskSemanticIntent(
            objective=objective or self.user_intent,
            intents=intents,
            requiredCapabilities=list(self.capabilities.required_capabilities),
            forbiddenCapabilities=list(self.capabilities.forbidden_capabilities),
            forbiddenActions=list(self.forbidden_actions),
            knowledgeDependency=deps.knowledge,
            ragPreference=self.rag_preference,
            requiresTool=deps.tool,
            requiresExternal=deps.external_system,
            requiresMemory=deps.memory,
            explanationOnly=self.explanation_only,
            hasAttachments=deps.attachment,
            mixedCapabilityRequest=deps.tool and deps.knowledge is not KnowledgeDependency.NONE,
            confidence=self.confidence,
            reasons=list(self.reason_codes),
            isContinuation=self.continuation.is_continuation,
            trustedReferenceResolvable=self.reference.resolvable_from_trusted_history,
            sideEffect=deps.side_effect,
            requestedEffects=list(self.requested_effects),
            trustedHistoryResolution=self.reference.trusted_history_resolution,
        )
