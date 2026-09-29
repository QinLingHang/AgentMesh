from app.rag.retrieval_budget import (
    AdaptiveCandidateBudgetPolicy,
)


def test_base_budget_preserves_final_top_k():
    policy = AdaptiveCandidateBudgetPolicy()

    budget = policy.resolve(
        final_top_k=5,
        round_index=0,
        enable_multi_query=False,
        enable_decomposition=False,
    )

    assert budget.final_top_k == 5
    assert budget.retrieval_top_k == 5
    assert budget.candidate_pool_k == 5
    assert budget.expanded is False
    assert budget.reason == "base"


def test_multi_query_budget_expands_by_one_point_five():
    policy = AdaptiveCandidateBudgetPolicy()

    budget = policy.resolve(
        final_top_k=5,
        round_index=0,
        enable_multi_query=True,
        enable_decomposition=False,
    )

    assert budget.retrieval_top_k == 8
    assert budget.candidate_pool_k == 20
    assert budget.expanded is True
    assert budget.reason == "multi_query"


def test_decomposition_budget_expands_by_two():
    policy = AdaptiveCandidateBudgetPolicy()

    budget = policy.resolve(
        final_top_k=5,
        round_index=0,
        enable_multi_query=False,
        enable_decomposition=True,
    )

    assert budget.retrieval_top_k == 10
    assert budget.candidate_pool_k == 20
    assert budget.reason == "decomposition"


def test_later_round_expands_after_insufficient_evidence():
    policy = AdaptiveCandidateBudgetPolicy()

    budget = policy.resolve(
        final_top_k=5,
        round_index=1,
        enable_multi_query=False,
        enable_decomposition=False,
    )

    assert budget.retrieval_top_k == 10
    assert budget.candidate_pool_k == 20
    assert budget.reason == "evidence_retry"


def test_budget_is_bounded_but_never_below_final_top_k():
    policy = AdaptiveCandidateBudgetPolicy(hard_cap=20)

    capped = policy.resolve(
        final_top_k=10,
        round_index=1,
        enable_multi_query=True,
        enable_decomposition=True,
    )

    assert capped.retrieval_top_k == 20
    assert capped.candidate_pool_k == 20

    caller_above_cap = policy.resolve(
        final_top_k=25,
        round_index=1,
        enable_multi_query=True,
        enable_decomposition=True,
    )

    assert caller_above_cap.final_top_k == 25
    assert caller_above_cap.retrieval_top_k == 25
    assert caller_above_cap.candidate_pool_k == 25
