from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class BoundedUpstreamContext:
    text: str
    original_chars: int
    included_chars: int
    truncated_items: int
    item_count: int


def _truncate_text(value: str, limit: int) -> tuple[str, bool]:
    text = str(value or "")
    if len(text) <= limit:
        return text, False
    marker = "\n[... upstream output truncated ...]\n"
    remaining = max(0, limit - len(marker))
    head = remaining // 2
    tail = remaining - head
    if tail:
        return text[:head] + marker + text[-tail:], True
    return text[:head] + marker, True


def build_bounded_upstream_context(
    upstream_outputs: Mapping[str, Any],
    *,
    per_item_chars: int = 6000,
    total_chars: int = 12000,
) -> BoundedUpstreamContext:
    """Build a bounded, provenance-labelled context for downstream DAG nodes.

    Upstream Agent output is untrusted model text and may be arbitrarily large.
    Feeding every completed sibling result back into the next model call without
    a bound can create runaway prompt growth, latency and provider timeouts.
    This helper preserves source labels and both the beginning and end of each
    result while enforcing deterministic per-item and total budgets.
    """

    per_item_chars = max(256, int(per_item_chars))
    total_chars = max(per_item_chars, int(total_chars))

    parts: list[str] = []
    original_chars = 0
    included_chars = 0
    truncated_items = 0

    for upstream_node_id, upstream_result in upstream_outputs.items():
        try:
            raw_text = str(upstream_result[1])
        except Exception:
            raw_text = str(upstream_result)

        original_chars += len(raw_text)
        remaining_total = total_chars - included_chars
        if remaining_total <= 0:
            truncated_items += 1
            continue

        item_budget = min(per_item_chars, remaining_total)
        bounded, truncated = _truncate_text(raw_text, item_budget)
        if truncated:
            truncated_items += 1

        label = f"[Upstream {upstream_node_id}]\n"
        # Source labels are metadata, not part of the text-content budget.
        parts.append(label + bounded)
        included_chars += len(bounded)

    return BoundedUpstreamContext(
        text="\n\n".join(parts),
        original_chars=original_chars,
        included_chars=included_chars,
        truncated_items=truncated_items,
        item_count=len(upstream_outputs),
    )
