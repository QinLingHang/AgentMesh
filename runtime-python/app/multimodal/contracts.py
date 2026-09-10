from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class RetrievalMode(str, Enum):
    TEXT = "text"
    VISUAL = "visual"
    HYBRID = "hybrid"


class VisualType(str, Enum):
    SCREENSHOT = "screenshot"
    DIAGRAM = "diagram"
    ARCHITECTURE = "architecture"
    CHART = "chart"
    TABLE = "table"
    DOCUMENT_PAGE = "document_page"
    GENERAL_IMAGE = "general_image"


@dataclass(frozen=True, slots=True)
class VisionObservation:
    summary: str
    visual_type: str = VisualType.GENERAL_IMAGE.value
    visible_text: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    relationships: tuple[str, ...] = ()
    key_facts: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def searchable_text(self) -> str:
        parts: list[str] = [self.summary.strip()]
        if self.visible_text:
            parts.append("Visible text: " + " | ".join(self.visible_text))
        if self.entities:
            parts.append("Entities: " + ", ".join(self.entities))
        if self.relationships:
            parts.append("Relationships: " + " | ".join(self.relationships))
        if self.key_facts:
            parts.append("Key facts: " + " | ".join(self.key_facts))
        return "\n".join(part for part in parts if part.strip()).strip()


class VisionAnalyzer(Protocol):
    async def analyze_image(
        self,
        *,
        content: bytes,
        media_type: str,
        source_name: str,
        page_number: int | None = None,
        task: str | None = None,
    ) -> VisionObservation:
        ...


@dataclass(frozen=True, slots=True)
class MultimodalIngestionStats:
    total_documents: int
    text_chunks: int
    visual_evidence: int
    page_count: int
    visual_status: str
    visual_error: str = ""
