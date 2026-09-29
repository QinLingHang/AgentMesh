from __future__ import annotations

import re

from app.rag.chunking.contracts import ChunkSpan, ChunkingPolicy


_SENTENCE_END_RE = re.compile(r"[。！？!?；;]\s*|(?<!\b[A-Z])\.\s+")


def legacy_fixed_window_spans(
    text: str,
    *,
    policy: ChunkingPolicy,
) -> list[ChunkSpan]:
    """Preserve the old fixed-window behavior for genuinely unstructured text."""
    result: list[ChunkSpan] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + policy.max_chars)
        trimmed_start, trimmed_end = _trim_span(text, start, end)
        if trimmed_end > trimmed_start:
            result.append(
                ChunkSpan(
                    start=trimmed_start,
                    end=trimmed_end,
                    split_reason="fixed_window_fallback",
                )
            )
        if end >= len(text):
            break
        next_start = end - policy.overlap_chars
        # Trimming can move the visible chunk start forward over whitespace.
        # With an overlap close to the hard max, the next raw window may then
        # trim back to the *same* source start, producing duplicate-start
        # chunks and pathological work. Advance beyond the emitted start while
        # preserving as much requested overlap as possible.
        next_start = max(next_start, trimmed_start + 1)
        if next_start <= start:
            next_start = end
        start = min(next_start, end)
    return result


def split_oversized_span(
    text: str,
    *,
    span_start: int,
    span_end: int,
    policy: ChunkingPolicy,
) -> list[ChunkSpan]:
    """Recursively split only an oversized source span.

    The splitter prefers paragraph/newline/sentence/lexical boundaries. It may
    increase the final overlap slightly to avoid creating a tiny terminal chunk,
    but it never exceeds the hard max and always makes forward progress.
    """
    span_start, span_end = _trim_span(text, span_start, span_end)
    if span_end <= span_start:
        return []
    if span_end - span_start <= policy.max_chars:
        return [ChunkSpan(span_start, span_end, "natural_block")]

    result: list[ChunkSpan] = []
    start = span_start

    while start < span_end:
        hard_end = min(span_end, start + policy.max_chars)
        if hard_end >= span_end:
            end = span_end
        else:
            # If the normal overlap would leave an undersized final fragment,
            # shorten this chunk just enough to keep the tail useful.
            target_end = hard_end
            normal_next = hard_end - policy.overlap_chars
            if span_end - normal_next < policy.min_chars:
                rebalanced = span_end - policy.min_chars + policy.overlap_chars
                if rebalanced > start:
                    target_end = min(hard_end, rebalanced)

            end = _find_preferred_break(
                text,
                start=start,
                target_end=target_end,
                min_chars=policy.min_chars,
            )
            if end <= start:
                end = target_end

        trimmed_start, trimmed_end = _trim_span(text, start, end)
        if trimmed_end > trimmed_start:
            result.append(
                ChunkSpan(
                    start=trimmed_start,
                    end=trimmed_end,
                    split_reason="oversized_recursive_split",
                )
            )

        if end >= span_end:
            break

        next_start = _aligned_overlap_start(
            text,
            end=end,
            lower_bound=span_start,
            overlap=policy.overlap_chars,
        )

        # Final-fragment guard. Prefer a slightly larger overlap to a useless
        # sub-minimum tail when the source span makes that possible.
        if 0 < span_end - next_start < policy.min_chars:
            desired = max(span_start, span_end - policy.min_chars)
            if desired < end:
                next_start = _safe_backward_boundary(
                    text,
                    candidate=desired,
                    lower=span_start,
                )
                if next_start >= end:
                    next_start = desired

        next_start = _skip_whitespace_forward(text, next_start, span_end)
        if next_start <= start:
            next_start = end
        start = next_start

    return result


def _find_preferred_break(
    text: str,
    *,
    start: int,
    target_end: int,
    min_chars: int,
) -> int:
    if target_end <= start:
        return start

    window_length = target_end - start
    # Never select a pretty boundary so early that it recreates V1's tiny-chunk
    # failure. The minimum is a preference, while 55% keeps custom tiny windows
    # viable when min_chars is itself small.
    floor = max(start + 1, start + min(min_chars, int(window_length * 0.70)))
    floor = min(floor, target_end)
    fragment = text[floor:target_end]

    for pattern in ("\n\n", "\n"):
        position = fragment.rfind(pattern)
        if position >= 0:
            return floor + position + len(pattern)

    sentence_end: int | None = None
    for match in _SENTENCE_END_RE.finditer(fragment):
        sentence_end = match.end()
    if sentence_end is not None:
        return floor + sentence_end

    # Lexical boundaries come before raw character fallback so identifiers,
    # URLs and API_KEY-like tokens are not split when an adjacent separator is
    # available.
    for separator in ("。", "！", "？", "；", ";", "，", ",", " ", "\t"):
        position = fragment.rfind(separator)
        if position >= 0:
            return floor + position + len(separator)

    return target_end


def _aligned_overlap_start(
    text: str,
    *,
    end: int,
    lower_bound: int,
    overlap: int,
) -> int:
    if overlap <= 0:
        return end
    candidate = max(lower_bound, end - overlap)
    if candidate >= end:
        return end
    return _safe_forward_boundary(text, candidate=candidate, upper=end)


def _safe_forward_boundary(text: str, *, candidate: int, upper: int) -> int:
    if candidate >= upper:
        return upper
    max_shift = max(8, (upper - candidate) // 3)
    search_end = min(upper, candidate + max_shift)
    fragment = text[candidate:search_end]

    newline = fragment.find("\n")
    if newline >= 0 and candidate + newline + 1 < upper:
        return candidate + newline + 1

    sentence = _SENTENCE_END_RE.search(fragment)
    if sentence is not None and candidate + sentence.end() < upper:
        return candidate + sentence.end()

    for separator in (" ", "\t", ",", "，", ";", "；"):
        position = fragment.find(separator)
        if position >= 0 and candidate + position + 1 < upper:
            return candidate + position + 1
    return candidate


def _safe_backward_boundary(text: str, *, candidate: int, lower: int) -> int:
    if candidate <= lower:
        return lower
    max_shift = max(8, (candidate - lower) // 3)
    search_start = max(lower, candidate - max_shift)
    fragment = text[search_start:candidate]

    newline = fragment.rfind("\n")
    if newline >= 0:
        return search_start + newline + 1

    sentence_end: int | None = None
    for match in _SENTENCE_END_RE.finditer(fragment):
        sentence_end = match.end()
    if sentence_end is not None:
        return search_start + sentence_end

    for separator in (" ", "\t", ",", "，", ";", "；"):
        position = fragment.rfind(separator)
        if position >= 0:
            return search_start + position + 1
    return candidate


def _skip_whitespace_forward(text: str, start: int, end: int) -> int:
    while start < end and text[start].isspace():
        start += 1
    return start


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end
