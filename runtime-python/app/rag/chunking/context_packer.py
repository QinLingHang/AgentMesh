from __future__ import annotations

from app.rag.chunking.contracts import ChunkSpan, ChunkingPolicy, StructuralBlock
from app.rag.chunking.recursive_splitter import split_oversized_span


def pack_blocks(
    text: str,
    *,
    blocks: tuple[StructuralBlock, ...],
    policy: ChunkingPolicy,
) -> list[ChunkSpan]:
    """Pack adjacent structural blocks while preserving source-contiguous spans.

    A heading is a preferred boundary only after the current chunk is already
    useful. Small sections are therefore allowed to cross heading boundaries,
    avoiding V1's heading-driven over-fragmentation. Oversized regions alone are
    delegated to the recursive splitter.
    """
    if not blocks:
        return []

    output: list[ChunkSpan] = []
    buffer: list[StructuralBlock] = []

    def buffer_start() -> int:
        return buffer[0].start

    def buffer_end() -> int:
        return buffer[-1].end

    def buffer_length() -> int:
        return buffer_end() - buffer_start()

    def buffer_only_headings() -> bool:
        return bool(buffer) and all(block.starts_heading for block in buffer)

    def flush(reason: str) -> None:
        nonlocal buffer
        if not buffer:
            return
        start = buffer_start()
        end = buffer_end()
        if end > start:
            output.append(ChunkSpan(start=start, end=end, split_reason=reason))
        buffer = []

    for block in blocks:
        if block.length <= 0:
            continue

        if not buffer:
            if block.length > policy.max_chars:
                output.extend(
                    split_oversized_span(
                        text,
                        span_start=block.start,
                        span_end=block.end,
                        policy=policy,
                    )
                )
            else:
                buffer = [block]
            continue

        candidate_length = block.end - buffer_start()
        current_length = buffer_length()

        if candidate_length <= policy.max_chars:
            # A new heading is a clean stopping point only when the current
            # chunk has already reached the soft target. If it is small, retain
            # the heading and its following context in one contiguous chunk.
            if (
                block.starts_heading
                and current_length >= policy.target_chars
                and not buffer_only_headings()
            ):
                flush("soft_target_before_heading")
                buffer = [block]
                continue

            # Paragraph/row boundaries are also soft targets; they should not
            # force a short chunk merely because a newline exists.
            if (
                not block.starts_heading
                and current_length >= policy.target_chars
                and current_length >= policy.min_chars
                and not buffer_only_headings()
            ):
                flush("soft_target_reached")
                buffer = [block]
                continue

            buffer.append(block)
            continue

        # The next block cannot fit as a whole. If the buffer is too small (or
        # consists only of headings), split the contiguous combined region so
        # the heading/context is not emitted as a useless standalone chunk.
        if current_length < policy.min_chars or buffer_only_headings():
            output.extend(
                split_oversized_span(
                    text,
                    span_start=buffer_start(),
                    span_end=block.end,
                    policy=policy,
                )
            )
            buffer = []
            continue

        flush("hard_max_before_block")
        if block.length > policy.max_chars:
            output.extend(
                split_oversized_span(
                    text,
                    span_start=block.start,
                    span_end=block.end,
                    policy=policy,
                )
            )
        else:
            buffer = [block]

    if buffer:
        tail_start = buffer_start()
        tail_end = buffer_end()
        tail_length = tail_end - tail_start

        # Merge a tiny terminal natural block backward when doing so stays
        # within the hard max and does not collide with an overlapped split.
        if tail_length < policy.min_chars and output:
            previous = output[-1]
            if previous.end <= tail_start and tail_end - previous.start <= policy.max_chars:
                output[-1] = ChunkSpan(
                    start=previous.start,
                    end=tail_end,
                    split_reason="small_tail_merged",
                )
                buffer = []

    if buffer:
        flush("document_tail")

    return _deduplicate_exact_spans(output)


def _deduplicate_exact_spans(spans: list[ChunkSpan]) -> list[ChunkSpan]:
    result: list[ChunkSpan] = []
    seen: set[tuple[int, int]] = set()
    for span in spans:
        key = (span.start, span.end)
        if span.end <= span.start or key in seen:
            continue
        seen.add(key)
        result.append(span)
    return result
