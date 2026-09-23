#!/usr/bin/env python3
"""Collect all frozen P23 decisions through the real internal HTTP endpoint."""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:9572/internal/v1/p23/understand")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    catalog = json.loads(args.fixtures.read_text(encoding="utf-8"))
    fixtures = {item["fixtureId"]: item for item in catalog["fixtures"]}
    results = []
    for row in rows:
        fixture = fixtures[row["fixtureId"]]
        state = "NONE"
        if fixture.get("tasks"):
            state = "ONE_PENDING" if len(fixture["tasks"]) == 1 else "AMBIGUOUS"
        body = json.dumps({
            "schemaVersion": "p23.v2", "task": row["query"],
            "ragMode": fixture["input"]["ragMode"],
            "hasAttachments": bool(fixture.get("attachments")),
            "continuationState": state, "allowModel": False,
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(args.url, data=body, method="POST", headers={
            "Content-Type": "application/json", "X-Internal-Token": args.token,
        })
        started = time.perf_counter_ns()
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
            status = response.status
        elapsed = time.perf_counter_ns() - started
        results.append({
            "caseId": row["caseId"], "route": payload["executionRoute"],
            "handling": payload["disposition"], "latencyUs": elapsed / 1000,
            "modelCalls": payload["modelCalls"], "modelTokens": payload["modelTokens"],
            "analysisSource": payload["analysisSource"], "reasonCodes": payload["reasonCodes"],
            "httpStatus": status, "source": "P23_REAL_INTERNAL_HTTP",
        })
    args.output.write_text("".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in results), encoding="utf-8")
    print(f"HTTP_PREDICTIONS: cases={len(results)} status200={sum(x['httpStatus'] == 200 for x in results)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
