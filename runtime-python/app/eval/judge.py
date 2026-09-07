from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from app.models.contracts import ModelMessage, ModelRequest
from app.schemas import RuntimeCitation


_DIMENSIONS = ("correctness", "groundedness", "citation_quality", "task_completion")
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")

_SENSITIVE_KEYS = ("authorization", "api_key", "apikey", "password", "token", "secret", "credential")


def _safe_eval_value(value: Any, *, depth: int = 0) -> Any:
    """Bound model-judge telemetry and fail closed on credential-like fields."""
    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:48]:
            key_text = str(key)[:120]
            if any(marker in key_text.lower() for marker in _SENSITIVE_KEYS):
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = _safe_eval_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_eval_value(item, depth=depth + 1) for item in value[:48]]
    if isinstance(value, str):
        lower = value.lower()
        if any(marker in lower for marker in (
            "authorization:", "bearer ", "api_key=", "apikey=", "password=", "token=", "secret="
        )):
            return "[REDACTED]"
        return value[:2500]
    return value


@dataclass(frozen=True, slots=True)
class JudgeRequest:
    task: str
    actual_answer: str
    reference_answer: str = ""
    evidence: tuple[str, ...] = ()
    citations: tuple[RuntimeCitation, ...] = ()
    tool_trace: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class JudgeResult:
    score: float
    dimension_scores: dict[str, float]
    reason: str
    passed: bool
    evaluator: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Judge(Protocol):
    async def evaluate(self, request: JudgeRequest) -> JudgeResult:
        ...


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in _TOKEN_RE.findall(text or "") if item.strip()}


def _overlap(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a:
        return 1.0 if not b else 0.0
    return min(1.0, len(a & b) / max(1, len(a)))


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 6)


class DeterministicMockJudge:
    name = "v2_deterministic_judge"

    async def evaluate(self, request: JudgeRequest) -> JudgeResult:
        answer = request.actual_answer.strip()
        task_completion = 1.0 if answer else 0.0
        correctness = (
            _overlap(request.reference_answer, answer)
            if request.reference_answer.strip()
            else min(1.0, len(answer) / 120.0)
        )
        evidence_text = "\n".join(request.evidence)
        groundedness = (
            _overlap(answer, evidence_text)
            if evidence_text.strip()
            else (1.0 if not request.citations else 0.0)
        )
        if request.citations:
            citation_quality = sum(_clamp(item.score) for item in request.citations) / len(request.citations)
        else:
            citation_quality = 1.0 if not evidence_text.strip() else 0.0

        dimensions = {
            "correctness": _clamp(correctness),
            "groundedness": _clamp(groundedness),
            "citation_quality": _clamp(citation_quality),
            "task_completion": _clamp(task_completion),
        }
        score = _clamp(sum(dimensions.values()) / len(dimensions))
        return JudgeResult(
            score=score,
            dimension_scores=dimensions,
            reason="deterministic test-safe judge",
            passed=score >= 0.70 and task_completion > 0,
            evaluator=self.name,
            metadata={"referenceProvided": bool(request.reference_answer.strip())},
        )


class ModelJudge:
    name = "v2_model_judge"

    def __init__(self, model_runtime: Any, *, threshold: float = 0.70) -> None:
        self.model_runtime = model_runtime
        self.threshold = _clamp(threshold)

    async def evaluate(self, request: JudgeRequest) -> JudgeResult:
        evidence = [item[:2500] for item in request.evidence[:8]]
        payload = {
            "task": request.task[:4000],
            "reference_answer": request.reference_answer[:4000],
            "actual_answer": request.actual_answer[:8000],
            "evidence": evidence,
            "citations": [item.model_dump(by_alias=True) for item in request.citations[:12]],
            "tool_trace": [_safe_eval_value(dict(item)) for item in request.tool_trace[:12]],
        }
        prompt = (
            "Evaluate an Agent answer. Return JSON only: score (0..1), "
            "dimension_scores with correctness, groundedness, citation_quality, task_completion, "
            "reason, passed. Do not include secrets. Input:\n" + json.dumps(payload, ensure_ascii=False)
        )
        response = await self.model_runtime.gateway.generate(
            ModelRequest(
                model=str(getattr(self.model_runtime, "model", "")),
                messages=[
                    ModelMessage(role="system", content="You are AgentMesh evaluation judge. Output strict JSON."),
                    ModelMessage(role="user", content=prompt),
                ],
                temperature=0.0,
            )
        )
        value = json.loads(response.content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
        if not isinstance(value, dict):
            raise ValueError("judge response must be object")
        raw_dims = value.get("dimension_scores") or value.get("dimensionScores") or {}
        if not isinstance(raw_dims, dict):
            raise ValueError("judge dimension_scores must be object")
        dims = {name: _clamp(float(raw_dims.get(name, 0.0))) for name in _DIMENSIONS}
        score = _clamp(float(value.get("score", sum(dims.values()) / len(dims))))
        return JudgeResult(
            score=score,
            dimension_scores=dims,
            reason=str(value.get("reason") or "model judge")[:1000],
            passed=bool(value.get("passed", score >= self.threshold)),
            evaluator=self.name,
            metadata={"model": response.model, "provider": response.provider},
        )
