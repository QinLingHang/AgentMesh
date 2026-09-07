#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# Support both documented entry points from the runtime-python directory:
#   python scripts/run_v2_eval.py
#   python -m scripts.run_v2_eval
# When Python executes a script by path it places scripts/ on sys.path rather
# than the runtime-python root, so bootstrap only that repository-local parent.
_RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(_RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_ROOT))

from app.eval import DeterministicMockJudge, ModelJudge, load_jsonl_dataset, run_evaluation_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an AgentMesh V2 evaluation dataset with the deterministic or model Judge."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "evals" / "v2_intelligence_cases.jsonl",
    )
    parser.add_argument("--judge", choices=("deterministic", "model"), default="deterministic")
    parser.add_argument("--output", type=Path, default=None, help="optional JSON result path")
    return parser.parse_args()


def _result_payload(result: Any, judge_name: str, dataset: Path) -> dict[str, Any]:
    return {
        "dataset": str(dataset),
        "judge": judge_name,
        "total": result.total,
        "passed": result.passed,
        "failed": result.failed,
        "meanScore": result.mean_score,
        "cases": [
            {
                "caseId": item.case_id,
                "score": item.judge.score,
                "passed": item.judge.passed,
                "dimensionScores": item.judge.dimension_scores,
                "reason": item.judge.reason,
                "evaluator": item.judge.evaluator,
                "metadata": item.judge.metadata,
            }
            for item in result.cases
        ],
    }


async def main() -> int:
    args = parse_args()
    dataset = args.dataset.resolve()
    cases = load_jsonl_dataset(dataset)
    if not cases:
        raise SystemExit("evaluation dataset is empty")

    if args.judge == "deterministic":
        judge = DeterministicMockJudge()
    else:
        # Reuse the production Model Gateway configuration without starting the
        # whole Runtime server. This path is intentionally environment-dependent
        # and can incur provider cost; deterministic evaluation remains the
        # mandatory offline regression path.
        from app.plugins.model import create_model_plugin

        plugin = create_model_plugin()
        runtime = SimpleNamespace(gateway=plugin.gateway, model=plugin.model)
        judge = ModelJudge(runtime)

    result = await run_evaluation_dataset(cases, judge)
    payload = _result_payload(result, getattr(judge, "name", type(judge).__name__), dataset)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output is not None:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")

    return 0 if result.failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
