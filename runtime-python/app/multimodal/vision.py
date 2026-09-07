from __future__ import annotations

import base64
import json
import re
from typing import Any

from app.models.contracts import ModelInputAttachment, ModelMessage, ModelRequest
from app.multimodal.contracts import VisionObservation, VisualType


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _bounded_strings(value: Any, *, limit: int = 24, width: int = 240) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value[:limit]:
        text = str(item).strip()
        if not text:
            continue
        result.append(text[:width])
    return tuple(result)


def _parse_observation(payload: str) -> VisionObservation:
    cleaned = _JSON_FENCE_RE.sub("", payload.strip()).strip()
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("vision analysis response must be a JSON object")

    summary = str(value.get("summary") or "").strip()
    if not summary:
        raise ValueError("vision analysis response missing summary")

    visual_type = str(value.get("visual_type") or value.get("visualType") or VisualType.GENERAL_IMAGE.value).strip().lower()
    allowed = {item.value for item in VisualType}
    if visual_type not in allowed:
        visual_type = VisualType.GENERAL_IMAGE.value

    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    return VisionObservation(
        summary=summary[:4000],
        visual_type=visual_type,
        visible_text=_bounded_strings(value.get("visible_text") or value.get("visibleText")),
        entities=_bounded_strings(value.get("entities")),
        relationships=_bounded_strings(value.get("relationships")),
        key_facts=_bounded_strings(value.get("key_facts") or value.get("keyFacts")),
        metadata=dict(metadata),
    )


class DeterministicVisionAnalyzer:
    """Stable, no-network analyzer used by tests and mock deployments.

    It deliberately does not pretend to understand arbitrary pixels. The
    summary describes the supplied asset deterministically and tests can use
    ``fixture_observations`` keyed by source name to provide semantic fixtures.
    """

    def __init__(self, fixture_observations: dict[str, VisionObservation] | None = None) -> None:
        self.fixture_observations = dict(fixture_observations or {})

    async def analyze_image(
        self,
        *,
        content: bytes,
        media_type: str,
        source_name: str,
        page_number: int | None = None,
        task: str | None = None,
    ) -> VisionObservation:
        if source_name in self.fixture_observations:
            return self.fixture_observations[source_name]

        location = f" page {page_number}" if page_number is not None else ""
        summary = (
            f"Synthetic deterministic visual observation for {source_name}{location}. "
            f"Media type {media_type}; payload size {len(content)} bytes."
        )
        return VisionObservation(
            summary=summary,
            visual_type=(
                VisualType.DOCUMENT_PAGE.value
                if page_number is not None
                else VisualType.GENERAL_IMAGE.value
            ),
            key_facts=("deterministic mock observation",),
            metadata={"mock": True, "payloadBytes": len(content)},
        )


class ModelVisionAnalyzer:
    """Vision analyzer backed by the existing AgentMesh Model Gateway plugin."""

    def __init__(self, model_runtime: Any) -> None:
        self.model_runtime = model_runtime

    async def analyze_image(
        self,
        *,
        content: bytes,
        media_type: str,
        source_name: str,
        page_number: int | None = None,
        task: str | None = None,
    ) -> VisionObservation:
        provider = str(getattr(self.model_runtime, "provider", "") or "").strip().lower()
        vision_model = str(getattr(self.model_runtime, "vision_model", "") or "").strip()
        # Mock runtimes are deliberately deterministic and can use their normal
        # model identifier. Real runtimes must opt in with an explicit vision
        # model so visual ingestion never silently targets a text-only model.
        model = vision_model
        if not model and provider == "mock":
            model = str(getattr(self.model_runtime, "model", "") or "").strip()
        if not model:
            raise RuntimeError("vision-capable model is not configured")

        prompt = (
            "Analyze this knowledge asset for retrieval. Return JSON only with keys: "
            "summary, visual_type, visible_text, entities, relationships, key_facts, metadata. "
            "visual_type must be one of screenshot, diagram, architecture, chart, table, "
            "document_page, general_image. Capture visual relationships and trends, not just OCR. "
            f"Source: {source_name}."
        )
        if page_number is not None:
            prompt += f" PDF page: {page_number}."
        if task:
            prompt += f" Analysis focus: {task[:500]}."

        request = ModelRequest(
            model=model,
            messages=[
                ModelMessage(role="system", content="You are AgentMesh multimodal knowledge analyzer. Output strict JSON."),
                ModelMessage(role="user", content=prompt),
            ],
            temperature=0.0,
            attachments=[
                ModelInputAttachment(
                    name=source_name,
                    media_type=media_type,
                    content_base64=base64.b64encode(content).decode("ascii"),
                )
            ],
        )
        response = await self.model_runtime.gateway.generate(request)
        return _parse_observation(response.content)
