from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable

from app.schemas import KnowledgeCatalogItem
from app.semantics.contracts import KnowledgeDependency, TaskSemanticIntent

_ASCII = re.compile(r"[a-z0-9][a-z0-9_.:/\\-]*", re.IGNORECASE)
_CJK = re.compile(r"[\u3400-\u9fff]+")


def _features(text: str) -> set[str]:
    value = " ".join(str(text or "").casefold().split())
    result = set(_ASCII.findall(value))
    for run in _CJK.findall(value):
        if len(run) <= 4:
            result.add(run)
        for width in (2, 3, 4):
            for index in range(max(0, len(run) - width + 1)):
                result.add(run[index : index + width])
    return result


def _score(query: str, descriptor: str) -> float:
    left = _features(query)
    right = _features(descriptor)
    if not left or not right:
        return 0.0
    overlap = left & right
    if not overlap:
        return 0.0
    coverage = len(overlap) / max(1.0, math.sqrt(len(left) * max(1, len(right))))
    return min(1.0, coverage * 0.85 + min(0.2, len(overlap) * 0.035))


@dataclass(frozen=True, slots=True)
class KnowledgeCandidate:
    knowledge_base_id: int
    score: float
    reason: str
    explicit: bool = False

    def trace_dict(self) -> dict[str, object]:
        return {
            "knowledgeBaseId": self.knowledge_base_id,
            "score": round(float(self.score), 4),
            "reason": self.reason,
            "explicit": self.explicit,
        }


@dataclass(slots=True)
class KnowledgeDiscoveryResult:
    needed: bool
    candidates: list[KnowledgeCandidate] = field(default_factory=list)
    selected_knowledge_base_ids: list[int] = field(default_factory=list)
    reason_code: str = ""

    def trace_dict(self) -> dict[str, object]:
        return {
            "needed": self.needed,
            "candidates": [item.trace_dict() for item in self.candidates],
            "selectedKnowledgeBaseIds": list(self.selected_knowledge_base_ids),
            "reasonCode": self.reason_code,
        }


def discover_knowledge_bases(
    task: str,
    *,
    semantic: TaskSemanticIntent,
    catalog: Iterable[KnowledgeCatalogItem],
    explicitly_selected_ids: Iterable[int] = (),
    max_candidates: int = 4,
    force_needed: bool = False,
) -> KnowledgeDiscoveryResult:
    items = [item for item in catalog if item.accessible]
    explicit = {int(value) for value in explicitly_selected_ids if int(value) > 0}
    allowed_ids = {item.knowledge_base_id for item in items}
    explicit &= allowed_ids

    needed = force_needed or semantic.knowledge_dependency != KnowledgeDependency.NONE
    if semantic.rag_preference.value == "ENABLE":
        needed = True

    if explicit:
        selected = [item.knowledge_base_id for item in items if item.knowledge_base_id in explicit]
        candidates = [
            KnowledgeCandidate(
                knowledge_base_id=item.knowledge_base_id,
                score=1.0,
                reason="explicitly selected by user after authorization filtering",
                explicit=True,
            )
            for item in items
            if item.knowledge_base_id in explicit
        ]
        return KnowledgeDiscoveryResult(
            needed=needed,
            candidates=candidates,
            selected_knowledge_base_ids=selected,
            reason_code="EXPLICIT_SELECTION" if selected else "NO_AVAILABLE_SOURCE",
        )

    if not needed:
        return KnowledgeDiscoveryResult(
            needed=False,
            reason_code="NOT_NEEDED",
        )

    scored: list[KnowledgeCandidate] = []
    for item in items:
        descriptor = f"{item.name} {item.description} {item.scope}"
        score = _score(task, descriptor)
        reason = "metadata relevance"
        if semantic.has_attachments:
            # Attachments are request-local evidence, not a reason to suppress
            # governed project knowledge. Keep metadata ranking neutral.
            reason += "; request also contains attachment evidence"
        scored.append(
            KnowledgeCandidate(
                knowledge_base_id=item.knowledge_base_id,
                score=score,
                reason=reason,
            )
        )

    scored.sort(key=lambda item: (-item.score, item.knowledge_base_id))
    positive = [item for item in scored if item.score > 0]
    if positive:
        selected_candidates = positive[: max(1, max_candidates)]
    else:
        # Metadata is advisory, not a hard exclusion. For a task that genuinely
        # requires governed knowledge, search a small bounded subset and allow
        # evidence quality to decide whether expansion is needed.
        selected_candidates = scored[: min(max(1, max_candidates), 2)]

    selected = [item.knowledge_base_id for item in selected_candidates]
    return KnowledgeDiscoveryResult(
        needed=True,
        candidates=scored[: max(8, max_candidates)],
        selected_knowledge_base_ids=selected,
        reason_code="METADATA_MATCH" if positive else ("BOUNDED_FALLBACK" if selected else "NO_AVAILABLE_SOURCE"),
    )
