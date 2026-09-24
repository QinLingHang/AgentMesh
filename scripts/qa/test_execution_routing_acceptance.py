"""QA driver/harness regression tests; no services or Docker required."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExecutionRoutingAcceptanceDriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = load_module("execution_routing_acceptance_driver_test", "run_execution_routing_acceptance.py")
        cls.benchmark = load_module("execution_routing_benchmark_driver_test", "benchmark_execution_routing_http.py")

    def test_knowledge_runtime_predictions_argument_matches_driver_attribute(self):
        args = self.driver.build_arg_parser().parse_args([
            "--knowledge-runtime-predictions",
            "knowledge-runtime-predictions.jsonl",
        ])
        self.assertEqual(
            args.knowledge_runtime_predictions,
            "knowledge-runtime-predictions.jsonl",
        )
        self.assertFalse(hasattr(args, "baseline_predictions"))


    def test_relative_acceptance_paths_resolve_from_repository_root(self):
        resolved = self.driver.resolve_cli_path("qa-results/execution-routing-acceptance")
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(
            resolved,
            (self.driver.ROOT / "qa-results" / "execution-routing-acceptance").resolve(),
        )

    def test_browser_env_always_propagates_isolated_mysql_dsn(self):
        env = self.driver.browser_env(
            mode="ENABLED", real_stack_only=True, qa_mysql_dsn="qa-dsn-sentinel"
        )
        self.assertEqual(env["QA_TEST_MYSQL_DSN"], "qa-dsn-sentinel")
        self.assertEqual(env["V4_1_E2E_ROUTING_MODE"], "ENABLED")
        self.assertEqual(env["V4_1_E2E_ROUTING_REAL_STACK_ONLY"], "true")

    def test_performance_report_argument_is_explicit_and_backward_compatible(self):
        args = self.driver.build_arg_parser().parse_args([
            "--performance-report", "qa-results/performance-current.json"
        ])
        self.assertEqual(args.performance_report, "qa-results/performance-current.json")

    def test_windows_utf8_and_missing_stderr_never_mask_a_failure(self):
        self.assertEqual(self.driver.safe_tail(None), "")
        self.assertEqual(self.driver.safe_tail("中文错误".encode("utf-8")), "中文错误")
        self.assertIn("\ufffd", self.driver.safe_tail(b"\xff"))
        result = self.driver.run_gate("utf8", [sys.executable, "-c", "import sys; print('中文输出'); print('中文错误', file=sys.stderr)"], cwd=HERE)
        self.assertEqual(result["status"], "PASS")
        self.assertIn("中文输出", result["stdoutTail"])
        self.assertIn("中文错误", result["stderrTail"])

    def test_no_command_is_blocked_without_crashing_the_report(self):
        result = self.driver.run_gate("missing", ["routing-nonexistent-executable-__QA__"], cwd=HERE)
        self.assertEqual(result["status"], "BLOCKED")

    def test_report_validation_rejects_score_below_frozen_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "route.json"
            data = {"current": {"metrics": {
                "all": {"cases": 120, "routeCorrect": 119, "requiredRuntimeMissed": 0, "fastPathOverrouted": 1},
                "safety": {"cases": 29, "routeCorrect": 29},
            }}}
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertFalse(self.driver.validate_route_report(path)[0])
            data["current"]["metrics"]["all"].update(routeCorrect=120, fastPathOverrouted=0)
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertTrue(self.driver.validate_route_report(path)[0])

    def test_go_authoritative_merger_must_have_exact_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "handling.json"
            data = {
                "all": {"cases": 120, "handlingCorrect": 120},
                "safety": {"cases": 29, "handlingCorrect": 29},
                "goOwned": {"cases": 14, "handlingCorrect": 13},
                "errors": [],
            }
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertFalse(self.driver.validate_handling_report(path)[0])
            data["goOwned"]["handlingCorrect"] = 14
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertTrue(self.driver.validate_handling_report(path)[0])

    def test_performance_evidence_requires_explicit_qa_admission(self):
        row = {"route": {"mode": "direct"}, "resultReceived": True,
               "ttfbMs": 10, "ttftMs": 15, "totalMs": 20,
               "modelTotalTokens": 48, "modelTokenFieldObserved": True,
               "estimatedCost": 0.01, "estimatedCostFieldObserved": True}
        rows = [dict(row) for _ in range(20)]
        data = {
            "matchedEnvironmentConfirmed": True, "modelIdentity": "same-model-v1",
            "OFF": {"samples": 20, "ttfbMs": {"p95": 100}, "totalMs": {"p95": 1000}}, "ENABLED": {"samples": 20, "ttfbMs": {"p95": 200}, "totalMs": {"p95": 1200}},
            "raw": {"OFF": rows, "ENABLED": [dict(row) for _ in range(20)]},
            "qaAdmission": "NOT_REVIEWED", "qaAdmissionReason": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "performance.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertFalse(self.driver.validate_performance_report(path)[0])
            data.update(qaAdmission="PASS", qaAdmissionReason="Independent comparison against previously frozen criteria")
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertTrue(self.driver.validate_performance_report(path)[0])

    def test_performance_evidence_accepts_missing_ttft_for_completed_no_delta_samples(self):
        with_delta = {"route": {"mode": "direct"}, "resultReceived": True,
                      "ttfbMs": 10, "ttftMs": 15, "totalMs": 20,
                      "modelTotalTokens": 48, "modelTokenFieldObserved": True,
                      "estimatedCost": 0.01, "estimatedCostFieldObserved": True}
        no_delta = dict(with_delta, ttftMs=None)
        off_rows = [dict(no_delta if i % 4 == 0 else with_delta) for i in range(20)]
        enabled_rows = [dict(no_delta if i % 4 == 0 else with_delta) for i in range(20)]
        data = {
            "matchedEnvironmentConfirmed": True, "modelIdentity": "dashscope:qwen-plus:openai-compatible",
            "OFF": {"samples": 20, "ttfbMs": {"p95": 100}, "totalMs": {"p95": 1000}}, "ENABLED": {"samples": 20, "ttfbMs": {"p95": 200}, "totalMs": {"p95": 1200}},
            "raw": {"OFF": off_rows, "ENABLED": enabled_rows},
            "qaAdmission": "PASS",
            "qaAdmissionReason": "Independent comparison against previously frozen criteria",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "performance.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            valid, detail = self.driver.validate_performance_report(path)
            self.assertTrue(valid, detail)

            # A numeric TTFT still has to be ordered within the same request.
            data["raw"]["ENABLED"][0] = dict(with_delta, ttftMs=5)
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertFalse(self.driver.validate_performance_report(path)[0])


    def test_performance_evidence_rejects_frozen_latency_regression(self):
        row = {"route": {"mode": "direct"}, "resultReceived": True,
               "ttfbMs": 10, "ttftMs": 15, "totalMs": 20,
               "modelTotalTokens": 48, "modelTokenFieldObserved": True,
               "estimatedCost": 0.01, "estimatedCostFieldObserved": True}
        rows = [dict(row) for _ in range(20)]
        data = {
            "matchedEnvironmentConfirmed": True, "modelIdentity": "same-model-v1",
            "OFF": {"samples": 20, "ttfbMs": {"p95": 100}, "totalMs": {"p95": 1000}},
            "ENABLED": {"samples": 20, "ttfbMs": {"p95": 1701}, "totalMs": {"p95": 3101}},
            "raw": {"OFF": rows, "ENABLED": [dict(row) for _ in range(20)]},
            "qaAdmission": "PASS", "qaAdmissionReason": "Matched environment and independently reviewed",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "performance.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            valid, detail = self.driver.validate_performance_report(path)
            self.assertFalse(valid, detail)

    def test_missing_real_browser_never_becomes_a_gate_pass(self):
        rows = [{"name": "G03_frozen_route_120", "status": "PASS"},
                {"name": "G05_G08_case56_72_82_real_chrome", "status": "NOT_RUN"}]
        aggregate = self.driver.aggregate_gates(rows)
        self.assertNotEqual(aggregate["G05"]["status"], "PASS")
        self.assertNotEqual(aggregate["G08"]["status"], "PASS")
        self.assertNotEqual(aggregate["G12"]["status"], "PASS")

    def test_benchmark_does_not_mislabel_ttfb_as_ttft(self):
        row = {"ttfbMs": 10, "ttftMs": None, "totalMs": 20, "estimatedCost": None, "modelTotalTokens": None}
        summary = self.benchmark.summarize([row])
        self.assertEqual(summary["ttfbMs"]["p50"], 10)
        self.assertEqual(summary["ttftMs"]["samples"], 0)
        self.assertEqual(summary["estimatedCostSamples"], 0)
        self.assertEqual(summary["modelTokenSamples"], 0)


if __name__ == "__main__":
    unittest.main()
