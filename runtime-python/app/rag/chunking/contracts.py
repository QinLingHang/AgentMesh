from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StructuralBlock:
    """A source-aligned structural unit in normalized document text."""

    start: int
    end: int
    block_type: str
    heading_path: tuple[str, ...]
    section_id: str
    starts_heading: bool = False

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class ChunkSpan:
    """A source-aligned candidate chunk before RetrievalDocument projection."""

    start: int
    end: int
    split_reason: str

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class ChunkingPolicy:
    """Size policy derived from the backward-compatible chunk_text API.

    ``max_chars`` is the legacy ``chunk_size`` hard ceiling. ``target_chars``
    is deliberately soft, while ``min_chars`` is a packing preference rather
    than an absolute validity rule: pathological inputs must always make
    progress even when no legal boundary can satisfy every preference.
    """

    min_chars: int
    target_chars: int
    max_chars: int
    overlap_chars: int

    @classmethod
    def from_legacy(cls, *, chunk_size: int, overlap: int) -> "ChunkingPolicy":
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")
        if overlap < 0:
            raise ValueError("overlap must be >= 0")
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")

        # The default 500-char contract therefore becomes 200 / 450 / 500.
        # Tiny custom chunk sizes remain usable in focused tests instead of
        # being forced to an unrelated absolute minimum.
        min_chars = max(1, int(round(chunk_size * 0.40)))
        target_chars = max(min_chars, int(round(chunk_size * 0.90)))
        target_chars = min(target_chars, chunk_size)
        return cls(
            min_chars=min_chars,
            target_chars=target_chars,
            max_chars=chunk_size,
            overlap_chars=overlap,
        )
