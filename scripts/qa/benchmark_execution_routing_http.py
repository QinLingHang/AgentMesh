from __future__ import annotations

"""Measure matching isolated OFF/ENABLED QA stacks; never enable production.

This tool collects evidence, not a performance verdict. QA must independently
review thresholds/model parity and record an explicit admission decision.
"""

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


PROMPTS = (
    "解释一下 Go slice 和 array 的区别。",
    "把这句话改得更简洁：可靠的 Agent 平台需要清晰的执行边界。",
    "What is exponential backoff?",
    "用三句话解释什么是幂等。",
)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil((p / 100.0) * len(ordered)) - 1))
    return ordered[idx]


def run_once(base_url: str, token: str, conversation_id: int, prompt: str, case_index: int) -> dict:
    payload = {
        "conversationId": conversation_id,
        "clientRequestId": str(uuid.uuid4()),
        "task": prompt,
        "scheduler": "adaptive", "planner": "multi_objective",
        "executionMode": "auto", "synthesisMode": "auto",
        "modelSelection": {"mode": "auto"},
        "ragPolicy": {"mode": "AUTO", "scopes": ["PROJECT"], "selectedKnowledgeBaseIds": []},
        "attachmentIds": [],
        # A >=30s latency budget would force Durable independent of Execution Routing.
        "constraints": {"maxLatencyMs": 8000, "maxCost": 0.15, "minQuality": 0.8, "retryOnWorkerLoss": False},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/tasks/submit-stream",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    started = time.perf_counter()
    first_event_at = None
    first_delta_at = None
    route = None
    result = None
    errors = []
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            for raw in response:
                if not raw.strip():
                    continue
                now = time.perf_counter()
                if first_event_at is None:
                    first_event_at = now
                event = json.loads(raw.decode("utf-8"))
                kind = event.get("type")
                if kind == "route":
                    route = {"mode": event.get("mode"), "strategy": event.get("strategy")}
                elif kind == "delta":
                    # TTFB (route/status) is not TTFT (genuine content delta).
                    if first_delta_at is None and isinstance(event.get("delta"), str) and event["delta"]:
                        first_delta_at = now
                elif kind == "error":
                    errors.append("execution_error")  # Never persist sensitive error bodies.
                elif kind == "result":
                    result = event.get("result")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"benchmark HTTP failed for case {case_index}: HTTP {exc.code}") from None
    finished = time.perf_counter()
    if errors or not isinstance(result, dict) or not route:
        raise RuntimeError(f"benchmark missing successful route/result for case {case_index}; errors={len(errors)}")
    if result.get("status") not in ("COMPLETED", "completed"):
        raise RuntimeError(f"benchmark nonterminal result for case {case_index}: {result.get('status')!r}")
    obs = result.get("observability") or {}
    return {
        "promptCase": case_index,
        "ttfbMs": round(((first_event_at or finished) - started) * 1000, 3),
        "ttftMs": round((first_delta_at - started) * 1000, 3) if first_delta_at else None,
        "totalMs": round((finished - started) * 1000, 3),
        "route": route,
        "resultReceived": True,
        "estimatedCost": result.get("estimatedCost"),
        "modelTotalTokens": obs.get("modelTotalTokens"),
        "modelTokenFieldObserved": "modelTotalTokens" in obs,
        "estimatedCostFieldObserved": "estimatedCost" in result,
    }


def summarize(rows: list[dict]) -> dict:
    ttfb = [float(x["ttfbMs"]) for x in rows]
    ttft = [float(x["ttftMs"]) for x in rows if x["ttftMs"] is not None]
    total = [float(x["totalMs"]) for x in rows]
    known_costs = [float(x["estimatedCost"]) for x in rows if x.get("estimatedCost") is not None]
    known_tokens = [int(x["modelTotalTokens"]) for x in rows if x.get("modelTotalTokens") is not None]
    return {
        "samples": len(rows),
        "ttfbMs": {"p50": percentile(ttfb, 50), "p95": percentile(ttfb, 95), "mean": statistics.fmean(ttfb)},
        "ttftMs": {"p50": percentile(ttft, 50), "p95": percentile(ttft, 95), "samples": len(ttft)},
        "totalMs": {"p50": percentile(total, 50), "p95": percentile(total, 95), "mean": statistics.fmean(total)},
        "estimatedCostTotalKnown": sum(known_costs),
        "estimatedCostSamples": len(known_costs),
        "modelTotalTokensKnown": sum(known_tokens),
        "modelTokenSamples": len(known_tokens),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="OFF vs ENABLED real-HTTP evidence collection. Does not change server modes.")
    parser.add_argument("--off-url", required=True)
    parser.add_argument("--enabled-url", required=True)
    parser.add_argument("--off-token", required=True, help="QA JWT of OFF isolated stack; never stored in report")
    parser.add_argument("--enabled-token", required=True, help="QA JWT of ENABLED isolated stack; never stored in report")
    parser.add_argument("--off-conversation-id", required=True, type=int)
    parser.add_argument("--enabled-conversation-id", required=True, type=int)
    parser.add_argument("--model-id", required=True, help="Identical model/provider/version fingerprint verified by QA")
    parser.add_argument("--matched-environment-confirmed", action="store_true", help="QA confirms same machine/model/config and isolated accounts")
    parser.add_argument("--qa-admission", choices=("PASS", "FAIL", "NOT_REVIEWED"), default="NOT_REVIEWED")
    parser.add_argument("--qa-admission-reason", default="")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.samples < 4:
        parser.error("at least 4 samples required to cover all frozen prompts")
    if args.off_url.rstrip("/") == args.enabled_url.rstrip("/"):
        parser.error("OFF and ENABLED URLs must identify separate isolated stacks")
    if args.off_conversation_id <= 0 or args.enabled_conversation_id <= 0:
        parser.error("conversation IDs must be valid for their respective isolated stacks")
    if args.qa_admission != "NOT_REVIEWED" and not args.qa_admission_reason.strip():
        parser.error("QA admission decision requires a reason with pre-agreed criteria")

    configs = {
        "OFF": (args.off_url, args.off_token, args.off_conversation_id),
        "ENABLED": (args.enabled_url, args.enabled_token, args.enabled_conversation_id),
    }
    rows: dict[str, list[dict]] = {"OFF": [], "ENABLED": []}
    # Interleave to reduce load/thermal/model variability between full batches.
    for i in range(args.samples):
        for mode in ("OFF", "ENABLED") if i % 2 == 0 else ("ENABLED", "OFF"):
            url, token, conversation_id = configs[mode]
            rows[mode].append(run_once(url, token, conversation_id, PROMPTS[i % len(PROMPTS)], i % len(PROMPTS)))

    off = summarize(rows["OFF"])
    enabled = summarize(rows["ENABLED"])
    off_p95 = off["ttfbMs"]["p95"]
    report = {
        "schemaVersion": "execution-routing.performance.real-http.v2",
        "scope": "simple_model_only_requests",
        "modelIdentity": args.model_id,
        "matchedEnvironmentConfirmed": args.matched_environment_confirmed,
        "qaAdmission": args.qa_admission,
        "qaAdmissionReason": args.qa_admission_reason,
        "note": "TTFB is the first HTTP NDJSON event; TTFT requires a real delta. Missing tokens/cost must not be interpreted as zero.",
        "OFF": off, "ENABLED": enabled,
        "comparison": {
            "ttfbP95DeltaMs": round(enabled["ttfbMs"]["p95"] - off_p95, 3),
            "ttfbP95DeltaPct": round((enabled["ttfbMs"]["p95"] / off_p95 - 1) * 100, 3) if off_p95 > 0 else None,
            "totalP95DeltaMs": round(enabled["totalMs"]["p95"] - off["totalMs"]["p95"], 3),
            "modelTotalTokensRatio": round(enabled["modelTotalTokensKnown"] / off["modelTotalTokensKnown"], 6) if off["modelTotalTokensKnown"] > 0 else None,
            "estimatedCostRatio": round(enabled["estimatedCostTotalKnown"] / off["estimatedCostTotalKnown"], 6) if off["estimatedCostTotalKnown"] > 0 else None,
        },
        "raw": rows,
    }
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(dest), "OFF": off, "ENABLED": enabled, "qaAdmission": args.qa_admission}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
