from __future__ import annotations

"""Own isolated acceptance stacks and collect real OFF/ENABLED HTTP evidence."""

import argparse
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QA_JWT_SECRET = "agentmesh-performance-acceptance-jwt-secret-2026"
QA_GOVERNANCE_KEY = "agentmesh-qa-performance-governance-key-2026"
MODEL_PROVIDER = "mock"
MODEL_NAME = "agentmesh-performance-mock"


class HTTPRequestError(RuntimeError):
    def __init__(self, endpoint, status, code, message):
        super().__init__(f"endpoint={endpoint} status={status} code={code} message={message}")
        self.endpoint, self.status = endpoint, status


def redact_diagnostics(value: str, extra_secrets=()) -> str:
    for secret in (QA_JWT_SECRET, QA_GOVERNANCE_KEY, *extra_secrets):
        if secret: value = value.replace(str(secret), "[REDACTED]")
    for pattern, replacement in (
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1[REDACTED]"),
        (r"(?i)(bearer\s+)eyJ\S+", r"\1[REDACTED]"),
        (r"(?i)((?:jwt[_ -]?secret|password|api[_ -]?key)\s*[:=]\s*)\S+", r"\1[REDACTED]"),
        (r"(?i)(verification.*?code\s*[:=]\s*)\d{6}", r"\1[REDACTED]"),
    ): value = re.sub(pattern, replacement, value)
    return value


def file_tail(path: Path, secrets=(), lines=80) -> str:
    if not path.exists(): return "<log not created>"
    text = "".join(path.read_text(encoding="utf-8", errors="replace").splitlines(True)[-lines:])
    return redact_diagnostics(text.rstrip(), secrets)


def _redis_read(stream):
    marker, line = stream.read(1), stream.readline()
    if not marker or not line.endswith(b"\r\n"): raise RuntimeError("Malformed Redis response")
    value = line[:-2]
    if marker == b"+": return value.decode()
    if marker == b"-": raise RuntimeError(f"Redis error: {value.decode(errors='replace')}")
    if marker == b":": return int(value)
    if marker == b"$":
        length = int(value)
        if length == -1: return None
        data = stream.read(length)
        if stream.read(2) != b"\r\n": raise RuntimeError("Malformed Redis bulk response")
        return data.decode()
    if marker == b"*": return [_redis_read(stream) for _ in range(int(value))]
    raise RuntimeError("Unsupported Redis response")


def _redis_send(connection, stream, parts):
    encoded = [str(part).encode() for part in parts]
    connection.sendall(b"*%d\r\n" % len(encoded) + b"".join(b"$%d\r\n" % len(x) + x + b"\r\n" for x in encoded))
    return _redis_read(stream)


def redis_command(*parts):
    with socket.create_connection(("127.0.0.1", 6382), timeout=5) as connection:
        return _redis_send(connection, connection.makefile("rb"), parts)


def redis_database_count() -> int:
    response = redis_command("CONFIG", "GET", "databases")
    if not isinstance(response, list) or len(response) != 2 or response[0] != "databases":
        raise RuntimeError("Unable to determine Redis database count")
    return int(response[1])


def allocate_redis_databases(count: int) -> tuple[int, int]:
    if count < 2: raise RuntimeError(f"Performance acceptance requires two Redis databases; Redis exposes {count}")
    result = count - 2, count - 1
    if result[0] == result[1] or any(not 0 <= x < count for x in result): raise RuntimeError("Illegal Redis allocation")
    return result


def redis_db_command(db: int, *parts):
    if db < 0: raise ValueError("Redis database index must be non-negative")
    with socket.create_connection(("127.0.0.1", 6382), timeout=5) as connection:
        stream = connection.makefile("rb")
        _redis_send(connection, stream, ("SELECT", db))
        return _redis_send(connection, stream, parts)


def cleanup_redis_prefix(db: int, prefix: str) -> None:
    cursor = "0"
    while True:
        response = redis_db_command(db, "SCAN", cursor, "MATCH", f"{prefix}:*", "COUNT", 200)
        if not isinstance(response, list) or len(response) != 2: raise RuntimeError("Unexpected Redis SCAN response")
        cursor, keys = response
        if keys: redis_db_command(db, "DEL", *keys)
        if cursor == "0": return


def port_has_listener(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(.15)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def allocate_port(excluded: set[int]) -> int:
    for _ in range(100):
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0)); port = candidate.getsockname()[1]
        if port not in excluded and not port_has_listener(port):
            excluded.add(port); return port
    raise RuntimeError("Unable to allocate a free loopback port")


def wait_for_port(port: int, expected: bool, timeout=20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_has_listener(port) is expected: return True
        time.sleep(.1)
    return False


def request(method, url, body=None, token=""):
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    endpoint = urllib.parse.urlparse(url).path
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response: return json.load(response)
    except urllib.error.HTTPError as exc:
        try: payload = json.loads(exc.read().decode(errors="replace"))
        except Exception: payload = {}
        raise HTTPRequestError(endpoint, exc.code, payload.get("code", "unknown"), redact_diagnostics(str(payload.get("message", exc.reason)))) from exc


def authenticate_fixture(base_url, fixture, requester=request) -> str:
    login = requester("POST", f"{base_url}/api/auth/login", {"email": fixture["memberEmail"], "password": fixture["memberPassword"]})
    token = login.get("data", {}).get("accessToken")
    if not token: raise RuntimeError("Password login response did not contain an access token")
    profile = requester("GET", f"{base_url}/api/me", token=token)
    if profile.get("data", {}).get("email") != fixture["memberEmail"]: raise RuntimeError("Fixture identity mismatch")
    return token


def go_fixture(action, qa_dsn, database=""):
    command = ["go", "run", "./cmd/browser-e2e-fixture", action]
    if database: command += ["--database", database]
    result = subprocess.run(command, cwd=ROOT / "backend-go", env=os.environ | {"QA_TEST_MYSQL_DSN": qa_dsn},
                            text=True, encoding="utf-8", errors="replace", capture_output=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def common_stack_env(fixture, go_port, runtime_port, redis_db, namespace, stack_id):
    internal = f"agentmesh-performance-internal-{stack_id}"
    runtime = os.environ.copy() | {
        "INTERNAL_TOKEN": internal, "CONTROL_PLANE_INTERNAL_BASE_URL": f"http://127.0.0.1:{go_port}",
        "RUNTIME_WORKER_ENABLED": "false", "MODEL_PROVIDER": MODEL_PROVIDER, "MODEL_NAME": MODEL_NAME,
        "MODEL_ROUTER_ENABLED": "false", "REDIS_URL": f"redis://127.0.0.1:6382/{redis_db}",
        "MEMORY_KEY_PREFIX": namespace, "PERFORMANCE_QA_PREFIX": namespace,
    }
    go = os.environ.copy() | {
        "BUSINESS_PORT": str(go_port), "MYSQL_HOST": fixture["host"], "MYSQL_PORT": fixture["port"],
        "MYSQL_DATABASE": fixture["database"], "MYSQL_USER": fixture["user"], "MYSQL_PASSWORD": fixture["password"],
        "REDIS_ADDR": "127.0.0.1:6382", "REDIS_DB": str(redis_db), "PERFORMANCE_QA_PREFIX": namespace,
        "JWT_SECRET": QA_JWT_SECRET, "JWT_ISSUER": "agentmesh-performance-acceptance",
        "RUNTIME_BASE_URL": f"http://127.0.0.1:{runtime_port}", "RUNTIME_INTERNAL_TOKEN": internal,
        "DURABLE_RUNTIME_ENABLED": "false", "EMAIL_PROVIDER": "console", "GOVERNANCE_MASTER_KEY": QA_GOVERNANCE_KEY,
        "VERIFICATION_PEPPER": "agentmesh-performance-verification-pepper-2026", "TASK_RATE_LIMIT_PER_MINUTE": "1000",
    }
    return go, runtime


def build_stack_env(mode, fixture, go_port, runtime_port, redis_db, tag, qa_prefix):
    if mode not in {"OFF", "ENABLED"}: raise ValueError("mode must be OFF or ENABLED")
    go, runtime = common_stack_env(fixture, go_port, runtime_port, redis_db, qa_prefix, tag)
    go["EXECUTION_ROUTING_MODE"] = mode
    return go, runtime


def build_server(binary: Path, build_log: Path, cache: Path) -> None:
    binary.parent.mkdir(parents=True, exist_ok=True)
    with build_log.open("w", encoding="utf-8") as log:
        subprocess.run(["go", "build", "-mod=readonly", "-o", str(binary), "./cmd/server"], cwd=ROOT / "backend-go",
                       env=os.environ | {"GOCACHE": str(cache)}, stdout=log, stderr=subprocess.STDOUT, check=True)


def stop_owned_process(proc) -> bool:
    if proc is None: return True
    if proc.poll() is None:
        proc.terminate()
        try: proc.wait(10)
        except subprocess.TimeoutExpired:
            if os.name == "nt": subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            else: proc.kill()
            try: proc.wait(10)
            except subprocess.TimeoutExpired: return False
    return proc.poll() is not None


@dataclass
class StackLifecycle:
    mode: str; stack_id: str; go_port: int; runtime_port: int; redis_db: int; redis_namespace: str
    qa_dsn: str; python: str; binary: Path; log_dir: Path
    fixture: dict | None = None
    go_env: dict = field(default_factory=dict); runtime_env: dict = field(default_factory=dict)
    go_process: subprocess.Popen | None = None; runtime_process: subprocess.Popen | None = None
    token: str = ""; conversation_id: int = 0; timeline: list[str] = field(default_factory=list)

    @property
    def base_url(self): return f"http://127.0.0.1:{self.go_port}"

    def record(self, event): self.timeline.append(event)

    def prepare(self):
        self.record(f"allocated ports go={self.go_port} runtime={self.runtime_port}")
        self.record(f"Redis isolation selected db={self.redis_db} namespace={self.redis_namespace}")
        if port_has_listener(self.go_port) or port_has_listener(self.runtime_port): raise RuntimeError(f"{self.mode} stale listener before spawn")
        self.fixture = go_fixture("prepare", self.qa_dsn)
        if not self.fixture: raise RuntimeError("fixture prepare returned no data")
        self.record(f"fixture DB created={self.fixture['database']}")
        self.go_env, self.runtime_env = build_stack_env(self.mode, self.fixture, self.go_port, self.runtime_port, self.redis_db, self.stack_id, self.redis_namespace)

    def start(self):
        if not self.fixture: raise RuntimeError("fixture must be prepared first")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        runtime_log = (self.log_dir / "runtime.log").open("w", encoding="utf-8", buffering=1)
        go_log = (self.log_dir / "go.log").open("w", encoding="utf-8", buffering=1)
        self.runtime_process = subprocess.Popen([self.python, "-u", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(self.runtime_port)], cwd=ROOT / "runtime-python", env=self.runtime_env, stdout=runtime_log, stderr=subprocess.STDOUT)
        self.record(f"Runtime PID={self.runtime_process.pid}")
        self.go_process = subprocess.Popen([str(self.binary)], cwd=ROOT / "backend-go", env=self.go_env, stdout=go_log, stderr=subprocess.STDOUT)
        self.record(f"Go PID={self.go_process.pid}")
        self._ready(self.runtime_process, self.runtime_port, "/readyz", "Runtime")
        self._ready(self.go_process, self.go_port, "/health", "Go")
        self.record("readiness PASS")

    def _ready(self, proc, port, route, component):
        deadline = time.time() + 90
        while time.time() < deadline:
            if proc.poll() is not None: raise RuntimeError(f"{self.mode} {component} exited rc={proc.returncode}")
            if port_has_listener(port):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{route}", timeout=2) as response:
                        if response.status == 200: return
                except Exception: pass
            time.sleep(.25)
        raise RuntimeError(f"{self.mode} {component} readiness timeout")

    def bootstrap(self):
        if not self.fixture or not self.go_process or self.go_process.poll() is not None: raise RuntimeError("fixture/process ownership missing")
        self.token = authenticate_fixture(self.base_url, self.fixture)
        self.record("login PASS"); self.record("/api/me fixture identity PASS")
        request("POST", f"{self.base_url}/api/agents/seed-demo", token=self.token)
        request("POST", f"{self.base_url}/api/me/model-services", {"name": "Matched Performance Mock", "provider": MODEL_PROVIDER,
                "baseUrl": "https://example.invalid/v1", "modelName": MODEL_NAME, "visionModelName": "", "apiKey": "qa-only-not-used",
                "enabled": True, "autoRoute": True, "isDefault": True}, self.token)
        conversation = request("POST", f"{self.base_url}/api/conversations", {"title": "Execution Routing Performance QA"}, self.token)
        self.conversation_id = conversation.get("data", {}).get("id", 0)
        if not isinstance(self.conversation_id, int) or self.conversation_id <= 0: raise RuntimeError("invalid conversation ID")
        self.record(f"conversation PASS id={self.conversation_id}")

    def diagnostic(self, exc):
        secrets = tuple(x for x in ((self.fixture or {}).get("password", ""), (self.fixture or {}).get("memberPassword", ""), self.token) if x)
        return redact_diagnostics(f"stack={self.mode} error={exc}\ntimeline:\n  " + "\n  ".join(self.timeline) +
            f"\n--- Go log ---\n{file_tail(self.log_dir / 'go.log', secrets)}\n--- Runtime log ---\n{file_tail(self.log_dir / 'runtime.log', secrets)}", secrets)

    def shutdown_and_cleanup(self):
        self.record("shutdown started")
        stopped = stop_owned_process(self.go_process) and stop_owned_process(self.runtime_process)
        released = wait_for_port(self.go_port, False) and wait_for_port(self.runtime_port, False)
        self.record(f"shutdown processes={'PASS' if stopped else 'FAIL'}"); self.record(f"port release={'PASS' if released else 'FAIL'}")
        if not stopped or not released:
            self.record("fixture cleanup RETAINED because shutdown was not proven"); return False
        cleanup_redis_prefix(self.redis_db, self.redis_namespace); self.record("Redis namespace cleanup PASS")
        if self.fixture: go_fixture("cleanup", self.qa_dsn, self.fixture["database"]); self.record("fixture cleanup PASS")
        return True


def assert_config_parity(off, enabled):
    for key in ("JWT_SECRET", "JWT_ISSUER", "REDIS_ADDR", "DURABLE_RUNTIME_ENABLED", "EMAIL_PROVIDER", "GOVERNANCE_MASTER_KEY",
                "VERIFICATION_PEPPER", "TASK_RATE_LIMIT_PER_MINUTE"):
        if off.go_env[key] != enabled.go_env[key]: raise RuntimeError(f"Go config parity failed: {key}")
    for key in ("RUNTIME_WORKER_ENABLED", "MODEL_PROVIDER", "MODEL_NAME", "MODEL_ROUTER_ENABLED"):
        if off.runtime_env[key] != enabled.runtime_env[key]: raise RuntimeError(f"Runtime config parity failed: {key}")


def load_benchmark():
    path = ROOT / "scripts/qa/benchmark_execution_routing_http.py"
    spec = importlib.util.spec_from_file_location("performance_benchmark", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def validate_dry_run(stack, benchmark):
    row = benchmark.run_once(stack.base_url, stack.token, stack.conversation_id, benchmark.PROMPTS[0], 0)
    if not row.get("resultReceived") or not row.get("route") or not row.get("modelTokenFieldObserved") or not row.get("estimatedCostFieldObserved"):
        raise RuntimeError(f"{stack.mode} dry-run missing route/result/token/cost evidence")
    if row.get("modelTotalTokens") is None or row.get("estimatedCost") is None: raise RuntimeError(f"{stack.mode} dry-run values missing")
    stack.record("dry-run PASS (excluded from 20 samples)")


def benchmark_command(args, off, enabled):
    return [args.python, str(ROOT / "scripts/qa/benchmark_execution_routing_http.py"), "--off-url", off.base_url,
            "--enabled-url", enabled.base_url, "--off-token", off.token, "--enabled-token", enabled.token,
            "--off-conversation-id", str(off.conversation_id), "--enabled-conversation-id", str(enabled.conversation_id),
            "--model-id", f"{MODEL_PROVIDER}/{MODEL_NAME}/same-python-runtime", "--matched-environment-confirmed",
            "--qa-admission", "PASS", "--qa-admission-reason", "Same binary/machine/runtime/provider/model/config; isolated ports, databases, Redis DBs, users and conversations.",
            "--samples", "20", "--output", str(Path(args.output).resolve())]


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--qa-mysql-dsn", required=True); parser.add_argument("--python", required=True); parser.add_argument("--output", required=True)
    args = parser.parse_args(); run_id = uuid.uuid4().hex
    evidence = Path(args.output).resolve().parent / "performance"; build_root = evidence / run_id
    binary = build_root / "agentmesh-performance-server.exe"; stacks = []; failed = None; return_code = 1
    try:
        build_server(binary, build_root / "go-build.log", build_root / "gocache")
        excluded = set(); ports = [allocate_port(excluded) for _ in range(4)]; off_db, enabled_db = allocate_redis_databases(redis_database_count())
        stacks = [StackLifecycle("OFF", f"{run_id}-off", ports[0], ports[1], off_db, f"agentmesh:qa:performance:{run_id}:off", args.qa_mysql_dsn, args.python, binary, evidence / "off"),
                  StackLifecycle("ENABLED", f"{run_id}-enabled", ports[2], ports[3], enabled_db, f"agentmesh:qa:performance:{run_id}:enabled", args.qa_mysql_dsn, args.python, binary, evidence / "enabled")]
        for stack in stacks: failed = stack; stack.prepare(); stack.start(); stack.bootstrap()
        if stacks[0].fixture["database"] == stacks[1].fixture["database"]: raise RuntimeError("fixture DBs are not isolated")
        assert_config_parity(*stacks); benchmark = load_benchmark()
        for stack in stacks: failed = stack; validate_dry_run(stack, benchmark)
        failed = None; result = subprocess.run(benchmark_command(args, *stacks), cwd=ROOT); return_code = result.returncode
        for stack in stacks: stack.record("benchmark samples=20" if return_code == 0 else "benchmark FAILED")
    except Exception as exc:
        target = failed or (stacks[-1] if stacks else None)
        print(target.diagnostic(exc) if target else redact_diagnostics(f"allocation/build failed: {exc}"), file=sys.stderr)
        return_code = 1
    finally:
        cleanup_failed = False
        for stack in reversed(stacks):
            try: cleanup_failed |= not stack.shutdown_and_cleanup()
            except Exception as exc: stack.record(f"cleanup FAIL: {redact_diagnostics(str(exc))}"); cleanup_failed = True
            print(f"{stack.mode} lifecycle timeline:\n  " + "\n  ".join(stack.timeline), file=sys.stderr)
        if cleanup_failed: return_code = 1
    return return_code


if __name__ == "__main__": raise SystemExit(main())
