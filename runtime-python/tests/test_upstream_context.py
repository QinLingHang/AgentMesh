from app.services.upstream_context import build_bounded_upstream_context


def test_upstream_context_preserves_small_results_and_labels():
    result = build_bounded_upstream_context({
        "step-risk": ("GeneralAgent", "risk output", [], 0.0),
        "step-plan": ("GeneralAgent", "plan output", [], 0.0),
    })
    assert "[Upstream step-risk]\nrisk output" in result.text
    assert "[Upstream step-plan]\nplan output" in result.text
    assert result.original_chars == len("risk output") + len("plan output")
    assert result.included_chars == result.original_chars
    assert result.truncated_items == 0


def test_upstream_context_bounds_each_item_and_total_without_losing_provenance():
    result = build_bounded_upstream_context(
        {
            "step-a": ("Agent", "A" * 1000, [], 0.0),
            "step-b": ("Agent", "B" * 1000, [], 0.0),
            "step-c": ("Agent", "C" * 1000, [], 0.0),
        },
        per_item_chars=400,
        total_chars=800,
    )
    assert result.original_chars == 3000
    assert result.included_chars <= 800
    assert result.truncated_items >= 2
    assert "[Upstream step-a]" in result.text
    assert "upstream output truncated" in result.text
    assert len(result.text) < 1000
