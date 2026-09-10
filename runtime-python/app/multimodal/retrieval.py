from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.multimodal.contracts import RetrievalMode
from app.rag.runtime import RetrievalHit

if TYPE_CHECKING:
    from app.rag.query_intelligence import QueryAnalysis


_VISUAL_TERMS = {
    "图片", "截图", "图表", "曲线", "柱状图", "架构图", "流程图", "表格",
    "figure", "image", "screenshot", "chart", "diagram", "architecture diagram", "table",
}
_PAGE_TERMS = {
    "第几页", "哪一页", "页图", "page", "figure", "fig.", "图 1", "图1", "图 2", "图2",
}
_TEXT_TERMS = {
    "正文", "段落", "文字", "定义", "描述", "文本", "章节", "段", "paragraph", "text", "section", "definition",
}
_HYBRID_CONNECTORS = {
    "结合", "同时", "以及", "综合", "对照", "根据正文和", "根据文字和", "and", "together", "along with",
}

_VISUAL_REFERENCE_RE = re.compile(
    r"(?:图|figure|fig\.?)[\s#:_-]*\d+|这(?:张|幅)图|(?:图|图片|截图|图表|架构图|流程图)(?:中|里|上|所示)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RetrievalModeDecision:
    mode: RetrievalMode
    reason: str
    visual_score: int
    text_score: int


def classify_retrieval_mode(
    query: str,
    analysis: QueryAnalysis | None = None,
) -> RetrievalModeDecision:
    """Classify text/visual/hybrid retrieval without making model availability a hard dependency.

    The decision combines lexical visual/text signals with the existing Query Intelligence
    intent/complexity result. It is deterministic for regression tests while still sharing
    the platform's canonical query analysis rather than introducing a parallel router.
    """

    normalized = " ".join(query.strip().lower().split())
    visual_matches = sorted(term for term in _VISUAL_TERMS if term in normalized)
    page_matches = sorted(term for term in _PAGE_TERMS if term in normalized)
    text_matches = sorted(term for term in _TEXT_TERMS if term in normalized)
    connector_matches = sorted(term for term in _HYBRID_CONNECTORS if term in normalized)

    visual_score = len(visual_matches) * 3 + len(page_matches) * 2
    text_score = len(text_matches) * 2

    if analysis is not None:
        intent = str(getattr(getattr(analysis, "intent", None), "value", ""))
        complexity = str(getattr(getattr(analysis, "complexity", None), "value", ""))

        # Query Intelligence is a semantic routing hint, not evidence that the user
        # requested a different modality.  In particular, relational/comparison
        # questions about a figure are still visual-only unless the query also
        # explicitly asks for text/section evidence.  Earlier code increased the
        # text score for relational/high-complexity visual questions, which made
        # queries such as "图 3 中 Worker 与 Dispatcher 是什么关系" incorrectly
        # route to HYBRID.
        if intent in {"comparison", "multi_hop", "relational"} and visual_score > 0:
            visual_score += 1

    # Explicit references such as "图 3" / "Figure 2" / "这张图中" are
    # strong visual signals.  Avoid treating every Chinese word containing the
    # character "图" (for example "图数据库") as an image request.
    if _VISUAL_REFERENCE_RE.search(normalized):
        visual_score += 4

    # HYBRID requires an explicit request for both text and visual evidence.
    # Connectors alone (e.g. "结合") do not manufacture a text signal.
    explicit_hybrid = bool(connector_matches and visual_score > 0 and text_score > 0)
    if explicit_hybrid or (visual_score > 0 and text_score > 0):
        mode = RetrievalMode.HYBRID
    elif visual_score > 0:
        mode = RetrievalMode.VISUAL
    else:
        mode = RetrievalMode.TEXT

    signals: list[str] = []
    if visual_matches:
        signals.append("visual=" + ",".join(visual_matches[:4]))
    if page_matches:
        signals.append("page=" + ",".join(page_matches[:3]))
    if text_matches:
        signals.append("text=" + ",".join(text_matches[:4]))
    if connector_matches:
        signals.append("connector=" + ",".join(connector_matches[:3]))
    if analysis is not None:
        signals.append(f"intent={getattr(getattr(analysis, 'intent', None), 'value', '')}")
        signals.append(f"complexity={getattr(getattr(analysis, 'complexity', None), 'value', '')}")
    reason = "; ".join(part for part in signals if part and not part.endswith("=")) or "default text retrieval"

    return RetrievalModeDecision(
        mode=mode,
        reason=reason,
        visual_score=visual_score,
        text_score=text_score,
    )


def infer_retrieval_mode(query: str, analysis: QueryAnalysis | None = None) -> RetrievalMode:
    return classify_retrieval_mode(query, analysis).mode


def modality_filters(mode: RetrievalMode) -> tuple[str, ...]:
    if mode is RetrievalMode.TEXT:
        return ("text",)
    if mode is RetrievalMode.VISUAL:
        return ("image", "page", "chart", "table")
    return ("text", "image", "page", "chart", "table")


def filter_hits_for_mode(hits: Sequence[RetrievalHit], mode: RetrievalMode) -> list[RetrievalHit]:
    allowed = set(modality_filters(mode))
    result: list[RetrievalHit] = []
    for hit in hits:
        modality = str(hit.document.metadata.get("modality", "text")).strip().lower() or "text"
        if modality in allowed:
            result.append(hit)
    return result


def diversify_multimodal_hits(hits: Sequence[RetrievalHit], *, top_k: int) -> list[RetrievalHit]:
    """Deduplicate visual/page siblings while preserving ranked evidence."""
    result: list[RetrievalHit] = []
    seen: set[tuple[str, int | None, str]] = set()
    for hit in hits:
        metadata = hit.document.metadata
        document_id = str(metadata.get("documentId") or hit.document.id)
        page = metadata.get("pageNumber")
        try:
            page_number = int(page) if page is not None else None
        except (TypeError, ValueError):
            page_number = None
        modality = str(metadata.get("modality", "text"))
        key = (document_id, page_number, modality)
        if key in seen:
            continue
        seen.add(key)
        result.append(hit)
        if len(result) >= max(0, top_k):
            break
    return result
