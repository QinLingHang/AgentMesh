"""QA driver/harness regression tests; no services or Docker required."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ExecutionRoutingAcceptanceDriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = load_module("execution_routing_acceptance_driver_test", "run_execution_routing_acceptance.py")
        cls.benchmark = load_module("execution_routing_benchmark_driver_test", "benchmark_execution_routing_http.py")
        cls.performance = load_module("execution_routing_performance_stack_test", "run_execution_routing_performance.py")

    def test_performance_stack_jwt_secrets_are_valid_and_never_reported(self):
        fixture = {"host": "127.0.0.1", "port": "3310", "database": "qa", "user": "root", "password": "secret"}
        for mode, tag in (("OFF", "off"), ("ENABLED", "enabled")):
            go_env, _ = self.performance.build_stack_env(mode, fixture, 18000, 19000, 15, tag, f"qa:{tag}")
            self.assertIn("JWT_SECRET", go_env)
            self.assertGreaterEqual(len(go_env["JWT_SECRET"]), 32)
            self.assertEqual(go_env["EXECUTION_ROUTING_MODE"], mode)
        report_fields = Path(HERE / "benchmark_execution_routing_http.py").read_text(encoding="utf-8")
        self.assertNotIn('"JWT_SECRET":', report_fields)

    def test_performance_redis_databases_are_distinct_and_legal(self):
        off_db, enabled_db = self.performance.allocate_redis_databases(16)
        self.assertTrue(0 <= off_db < 16)
        self.assertTrue(0 <= enabled_db < 16)
        self.assertNotEqual(off_db, enabled_db)
        self.assertNotIn(16, (off_db, enabled_db))
        self.assertEqual((off_db, enabled_db), (14, 15))

    def test_performance_redis_allocation_fails_before_stack_when_insufficient(self):
        for count in (0, 1):
            with self.assertRaises(RuntimeError):
                self.performance.allocate_redis_databases(count)

    def test_performance_redis_prefixes_are_isolated_and_cleanup_is_scoped(self):
        fixture = {"host": "127.0.0.1", "port": "3310", "database": "qa", "user": "root", "password": "secret"}
        off_prefix = "agentmesh:qa:performance:run-id:off"
        enabled_prefix = "agentmesh:qa:performance:run-id:enabled"
        _, off_runtime = self.performance.build_stack_env("OFF", fixture, 18001, 19001, 14, "off", off_prefix)
        _, enabled_runtime = self.performance.build_stack_env("ENABLED", fixture, 18002, 19002, 15, "enabled", enabled_prefix)
        self.assertEqual(off_runtime["MEMORY_KEY_PREFIX"], off_prefix)
        self.assertEqual(enabled_runtime["MEMORY_KEY_PREFIX"], enabled_prefix)
        self.assertNotEqual(off_runtime["MEMORY_KEY_PREFIX"], enabled_runtime["MEMORY_KEY_PREFIX"])
        launcher = Path(HERE / "run_execution_routing_performance.py").read_text(encoding="utf-8").upper()
        self.assertNotIn("FLUSHALL", launcher)
        self.assertNotIn("FLUSHDB", launcher)
        self.assertIn('"MATCH", F"{PREFIX}:*"', launcher)

    def test_performance_bootstrap_uses_fixture_password_login_and_me(self):
        fixture = {"memberEmail": "fixture@example.test", "memberPassword": "fixture-password"}
        calls = []

        def fake_request(method, url, body=None, token=""):
            calls.append((method, url, body, token))
            if url.endswith("/api/auth/login"):
                return {"data": {"accessToken": "token-from-real-login-response"}}
            return {"data": {"email": fixture["memberEmail"]}}

        token = self.performance.authenticate_fixture("http://127.0.0.1:18001", fixture, fake_request)
        self.assertEqual(token, "token-from-real-login-response")
        self.assertEqual([call[1] for call in calls], [
            "http://127.0.0.1:18001/api/auth/login",
            "http://127.0.0.1:18001/api/me",
        ])
        self.assertEqual(calls[1][3], token)

    def test_performance_launcher_has_no_verification_registration_bootstrap(self):
        launcher = Path(HERE / "run_execution_routing_performance.py").read_text(encoding="utf-8")
        self.assertNotIn("/api/auth/email/code", launcher)
        self.assertNotIn("/api/auth/register/verify", launcher)
        self.assertIn('go_fixture("prepare", self.qa_dsn)', launcher)
        self.assertIn('f"{self.base_url}/api/conversations"', launcher)
        self.assertLess(launcher.index('f"{base_url}/api/me"'), launcher.index("def benchmark_command"))

    def test_performance_auth_rejects_missing_login_token_or_wrong_fixture_user(self):
        fixture = {"memberEmail": "fixture@example.test", "memberPassword": "fixture-password"}
        with self.assertRaises(RuntimeError):
            self.performance.authenticate_fixture("http://qa", fixture, lambda *args, **kwargs: {"data": {}})

        responses = iter((
            {"data": {"accessToken": "real-login-token"}},
            {"data": {"email": "different@example.test"}},
        ))
        with self.assertRaises(RuntimeError):
            self.performance.authenticate_fixture("http://qa", fixture, lambda *args, **kwargs: next(responses))

    def test_performance_diagnostics_redact_credentials(self):
        raw = "Authorization: Bearer eyJsecret JWT_SECRET=topsecret password=hunter2 api_key=abc verification code=123456"
        redacted = self.performance.redact_diagnostics(raw)
        for secret in ("eyJsecret", "topsecret", "hunter2", "abc", "123456"):
            self.assertNotIn(secret, redacted)

    def test_performance_server_is_built_once_without_go_run(self):
        launcher = Path(HERE / "run_execution_routing_performance.py").read_text(encoding="utf-8")
        self.assertIn('["go", "build", "-mod=readonly", "-o", str(binary), "./cmd/server"]', launcher)
        self.assertNotIn('["go", "run", "./cmd/server"]', launcher)
        self.assertEqual(launcher.count("build_server(binary,"), 1)

    def test_performance_dynamic_ports_are_unique_and_listener_free(self):
        excluded = set()
        ports = [self.performance.allocate_port(excluded) for _ in range(4)]
        self.assertEqual(len(set(ports)), 4)
        self.assertFalse(any(self.performance.port_has_listener(port) for port in ports))

    def test_performance_owned_process_shutdown_uses_only_owned_pid(self):
        proc = mock.Mock(pid=43210)
        proc.poll.side_effect = [None, 0]
        proc.wait.side_effect = [self.performance.subprocess.TimeoutExpired("owned", 10), 0]
        with mock.patch.object(self.performance.os, "name", "nt"), mock.patch.object(self.performance.subprocess, "run") as run:
            self.assertTrue(self.performance.stop_owned_process(proc))
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "43210", "/T", "/F"])

    def test_performance_cleanup_retains_fixture_when_shutdown_unproven(self):
        stack = self.performance.StackLifecycle("OFF", "id", 41001, 41002, 14, "qa:off", "dsn", "python", Path("server"), Path("logs"))
        stack.fixture = {"database": "agentmesh_browser_e2e_keep"}
        with mock.patch.object(self.performance, "stop_owned_process", return_value=False), \
             mock.patch.object(self.performance, "go_fixture") as fixture_cleanup, \
             mock.patch.object(self.performance, "cleanup_redis_prefix") as redis_cleanup:
            self.assertFalse(stack.shutdown_and_cleanup())
        fixture_cleanup.assert_not_called()
        redis_cleanup.assert_not_called()

    def test_performance_cleanup_orders_process_ports_redis_then_fixture(self):
        stack = self.performance.StackLifecycle("OFF", "id", 41001, 41002, 14, "qa:off", "dsn", "python", Path("server"), Path("logs"))
        stack.fixture = {"database": "agentmesh_browser_e2e_drop"}
        events = []
        with mock.patch.object(self.performance, "stop_owned_process", side_effect=lambda proc: events.append("stop") or True), \
             mock.patch.object(self.performance, "wait_for_port", side_effect=lambda *args: events.append("port") or True), \
             mock.patch.object(self.performance, "cleanup_redis_prefix", side_effect=lambda *args: events.append("redis")), \
             mock.patch.object(self.performance, "go_fixture", side_effect=lambda *args: events.append("fixture")):
            self.assertTrue(stack.shutdown_and_cleanup())
        self.assertEqual(events[-2:], ["redis", "fixture"])
        self.assertLess(events.index("port"), events.index("redis"))

    def test_performance_logs_are_direct_files_and_dry_run_precedes_benchmark(self):
        launcher = Path(HERE / "run_execution_routing_performance.py").read_text(encoding="utf-8")
        self.assertIn('(self.log_dir / "go.log").open', launcher)
        self.assertIn('(self.log_dir / "runtime.log").open', launcher)
        self.assertNotIn("stdout=subprocess.PIPE", launcher)
        self.assertLess(launcher.index("validate_dry_run(stack, benchmark)"), launcher.index("subprocess.run(benchmark_command"))

    def test_performance_common_config_parity_is_enforced(self):
        fixture = {"host": "h", "port": "1", "database": "d", "user": "u", "password": "p"}
        off = self.performance.StackLifecycle("OFF", "off", 1, 2, 14, "n:off", "dsn", "py", Path("b"), Path("l"))
        enabled = self.performance.StackLifecycle("ENABLED", "enabled", 3, 4, 15, "n:enabled", "dsn", "py", Path("b"), Path("l"))
        off.go_env, off.runtime_env = self.performance.build_stack_env("OFF", fixture, 1, 2, 14, "off", "n:off")
        enabled.go_env, enabled.runtime_env = self.performance.build_stack_env("ENABLED", fixture, 3, 4, 15, "enabled", "n:enabled")
        self.performance.assert_config_parity(off, enabled)
        enabled.runtime_env["MODEL_NAME"] = "mismatch"
        with self.assertRaises(RuntimeError): self.performance.assert_config_parity(off, enabled)

    def test_performance_dry_run_requires_real_token_and_cost_values(self):
        stack = mock.Mock(mode="OFF", base_url="http://qa", token="token", conversation_id=1)
        benchmark = mock.Mock(PROMPTS=("prompt",))
        benchmark.run_once.return_value = {"resultReceived": True, "route": {"mode": "direct"},
            "modelTokenFieldObserved": True, "estimatedCostFieldObserved": True,
            "modelTotalTokens": None, "estimatedCost": 0.0}
        with self.assertRaises(RuntimeError): self.performance.validate_dry_run(stack, benchmark)

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
