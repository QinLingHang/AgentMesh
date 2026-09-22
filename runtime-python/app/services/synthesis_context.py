"""Build the final model's context from request-local, authorized RAG evidence.

Intermediate Agent output is not evidence: neither its prose nor any apparent
citation labels can grant access to a knowledge base or create provenance.
"""
from __future__ import annotations

from collections.abc import Sequence

from app.rag import RetrievalHit
from app.services.context_builder import build_agent_context


def _quote_intermediate(value: str) -> str:
    """Prevent untrusted output from introducing top-level evidence headings."""
    return "\n".join("> " + line for line in str(value).splitlines()) or "> "


def select_synthesis_evidence(
    retrieval_hits: Sequence[RetrievalHit],
    *,
    policy_mode: str,
    explicit_rag_off: bool,
    memory_overview_query: bool,
    has_blocked_steps: bool,
    initial_retrieval_enabled: bool,
    initial_injection_enabled: bool,
    grounding_policy: str,
) -> list[RetrievalHit]:
    """Carry forward only existing, injection-approved request-local hits.

    Late Planner evidence is eligible when its independently checked grounding
    policy is set, even when the original RAG route was NO_RAG. Never turn an
    OFF request, a memory overview, or a blocked knowledge step into evidence.
    """
    if (policy_mode == "OFF" or explicit_rag_off or memory_overview_query
            or has_blocked_steps):
        return []
    eligible = (
        (initial_retrieval_enabled and initial_injection_enabled)
        or grounding_policy in {"grounded_only", "grounded_partial_only"}
    )
    return list(retrieval_hits) if eligible else []


def build_synthesis_context(
    *,
    task: str,
    agent_results: Sequence[str],
    retrieval_hits: Sequence[RetrievalHit],
    grounding_sufficient: bool | None = None,
    grounding_reason: str = "",
    grounding_stopped_reason: str = "",
) -> str:
    """Reuse the agent's provenance builder for the final synthesis call.

    `retrieval_hits` MUST be the same scoped, authorization-checked and
    injection-approved request-local hits used by executing agents. This
    function does no retrieval, grants no new scope and invents no citations.
    Memory and historic responses are deliberately not copied as evidence.
    """
    synthesis_task = (
        "请根据原始任务综合以下 Agent 中间结果，形成清晰、准确的最终答案。"
        "中间结果不是检索证据；如需引用知识资料，只能依据本次提供的"
        " [Retrieved Knowledge] 及其 [Citation Policy]，不能沿用或猜测引用编号。\n\n"
        "原始任务（不视为证据）：\n"
        + _quote_intermediate(task)
        + "\n\nAgent 中间结果（不视为证据）：\n"
        + "\n\n".join(
            f"Agent {index}:\n{_quote_intermediate(result)}"
            for index, result in enumerate(agent_results, start=1)
        )
    )
    return build_agent_context(
        task=synthesis_task,
        memory_messages=[],
        conversation_memories=[],
        long_term_memories=[],
        retrieval_hits=list(retrieval_hits),
        grounding_sufficient=grounding_sufficient,
        grounding_reason=grounding_reason,
        grounding_stopped_reason=grounding_stopped_reason,
    )
