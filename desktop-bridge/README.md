# AgentMesh Desktop Agent Bridge

Windows-first, loopback-only local execution bridge for AgentMesh.

Desktop Agent extends the original local-file bridge into one governed local-computer surface:

- `local.fs.*` — authorized file/folder access;
- `local.app.*` — discover, launch, open, focus, inspect and close registered applications;
- `local.tool.*` — run registered CLI tools such as Python, Git, Go, Node and FFmpeg;
- `local.terminal.*` — optional advanced PowerShell execution, disabled by default;
- `local.ui.*` — explicit Computer Use sessions for screenshot, windows, mouse, keyboard and Windows UI Automation.

The React browser never talks to this bridge directly and never receives the Desktop Bridge token. The normal path is:

```text
Browser
  -> Go Control Plane / governance
  -> Python Agent Runtime
  -> 127.0.0.1 Desktop Bridge
  -> local Windows computer
```

## Security model

Desktop Agent is powerful local code-execution functionality. Its boundaries are intentionally explicit.

### Loopback and authentication

- the bridge may bind only to `127.0.0.1`, `localhost` or `::1`;
- every bridge request requires `x-desktop-token`;
- Runtime accepts only a loopback Desktop Bridge URL;
- tokens are not written to the Desktop audit log or React state.

### Local files

Every `local.fs.*` path is resolved to its canonical target before authorization.

- access outside `DESKTOP_ALLOWED_ROOTS_JSON` is denied;
- read/write/delete are separate grants;
- symlink, Windows junction and reparse-point escape attempts are denied;
- an authorized root itself cannot be moved or deleted;
- common credential locations and key suffixes are denied unless that root explicitly opts into `allowSensitive=true`.

Protected defaults include `.ssh`, `.aws`, `.kube`, `.env`, `*.pem`, `*.key`, `*.p12` and `*.pfx`.

### CLI tools are not an OS sandbox

`local.tool.run` executes only a registered executable with an argv array and `shell=False` by default. Its working directory must be inside an authorized root.

However, **an authorized working directory is not a process sandbox**. Python, Node, Java and similar interpreters can access other OS resources once executed. For that reason:

- `local.tool.run` is always classified HIGH risk by AgentMesh;
- it always requires explicit approval before execution;
- secret-like environment variables are filtered from the child process environment;
- stdout/stderr are bounded and omitted from persistent Trace metadata;
- background runs are represented by a bridge-owned `processId` and can be long-polled/cancelled. `local.tool.run` and `local.tool.status` accept a bounded `waitSeconds` (up to the configured local maximum, 30 seconds by default), so long builds/tests do not consume one model turn per immediate poll.

On Windows, known `.cmd`/`.bat` wrappers such as `npm.cmd`, `pnpm.cmd`, `mvn.cmd` and `gradle.bat` use the fixed Windows command processor compatibility path. Arguments containing command-structure metacharacters (`& | < > ^ % !` or newlines) are rejected rather than treated as shell syntax.

### Advanced terminal

`local.terminal.run` is a separate capability and is **disabled by default**:

```text
DESKTOP_ALLOW_TERMINAL=false
```

When enabled it remains HIGH risk and requires explicit approval for every run. Desktop audit records only command length/hash metadata, not the terminal command text itself.

### Applications

Applications are discovered from a small known allowlist (`PATH` and Windows App Paths) or explicitly configured through `DESKTOP_ALLOWED_APPS_JSON`.

- launch/open require approval;
- opening a file/folder still requires an authorized local path;
- close is HIGH risk;
- a close without an explicit PID can terminate only application instances launched by this bridge, preventing an application alias from mass-terminating unrelated processes that share the same executable.

### Computer Use

GUI control is opt-in:

```text
DESKTOP_COMPUTER_USE_ENABLED=false
```

When enabled, AgentMesh must first execute the HIGH-risk `local.ui.session.start` action through its approval flow. Screen/window/mouse/keyboard/UI Automation calls require the returned, time-bounded session id. `local.ui.session.stop` is the emergency stop.

Dangerous OS shortcuts such as `Win+R`, `Win+X`, `Alt+F4` and `Ctrl+Alt+Delete` are rejected by the bridge. Window close remains a separate HIGH-risk confirmation action.

Screenshot bytes are never persisted into generic Tool Trace JSON. Runtime removes `imageBase64` and, when the selected personal model service has an explicit vision model, attaches the screenshot request-locally to the next model turn. Without a configured vision model, the model receives metadata with `visionAvailable=false` and should prefer Windows UI Automation rather than pretending it saw the screen.

### Audit

`DESKTOP_AUDIT_FILE` is metadata-oriented. It records operation category, outcome and bounded identifiers/paths as needed for accountability, but intentionally avoids:

- Desktop Bridge token;
- API/JWT credentials;
- file contents;
- screenshot Base64/pixels;
- typed text values;
- terminal command text;
- process stdout/stderr.

## Configuration

Copy `.env.example` values into your local environment or set them in PowerShell.

Example:

```powershell
$env:DESKTOP_BRIDGE_HOST = "127.0.0.1"
$env:DESKTOP_BRIDGE_PORT = "9583"
$env:DESKTOP_BRIDGE_TOKEN = "replace-with-a-long-random-token"
$env:DESKTOP_ALLOWED_ROOTS_JSON = '[{"path":"E:\\AIProject","read":true,"write":true,"delete":true,"allowSensitive":false}]'

# Optional complete Desktop Agent capabilities.
$env:DESKTOP_AUTO_DISCOVER_EXECUTABLES = "true"
$env:DESKTOP_ALLOW_TERMINAL = "false"
$env:DESKTOP_COMPUTER_USE_ENABLED = "true"
```

Custom registered apps/tools use JSON arrays:

```json
[
  {
    "id": "my-tool",
    "displayName": "My Tool",
    "executable": "E:\\Tools\\my-tool.exe"
  }
]
```

Use that payload in `DESKTOP_ALLOWED_TOOLS_JSON` or `DESKTOP_ALLOWED_APPS_JSON` respectively.

## Install and start

From `desktop-bridge`:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn desktop_bridge.app:app --host 127.0.0.1 --port 9583
```

The Python Runtime must use the same token and loopback URL through its existing Desktop Bridge settings.

## Windows dynamic acceptance

Run:

```powershell
python -m pytest -q
```

On Windows the suite contains a deterministic real GUI application and exercises:

- real screen capture;
- window discovery/focus;
- real mouse movement/click;
- real keyboard input/hotkeys;
- Windows UI Automation find/set/invoke;
- bridge session start/stop;
- junction/reparse-point escape protection;
- registered CLI execution/status/cancel;
- app-process close scoping;
- Windows batch-wrapper injection rejection.

Mandatory Windows acceptance must report **0 skipped tests**. Non-Windows development hosts return normally from Windows-specific checks rather than presenting that environment as proof of Windows Computer Use behavior.
