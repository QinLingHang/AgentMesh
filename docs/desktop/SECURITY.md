# Local Desktop Security Boundary

1. Desktop Bridge binds to loopback only. Non-loopback bind values are rejected at startup.
2. Every operation requires a high-entropy `x-desktop-token`. The browser never receives this token.
3. `DESKTOP_ALLOWED_ROOTS_JSON` is fail-closed. No configured root means no file access.
4. Grants separate `read`, `write`, and `delete` permissions.
5. Paths are canonicalized before authorization. Symlink/reparse-style escapes outside an authorized root are denied.
6. Common credential stores and secret files such as `.ssh`, `.aws`, `.kube`, `.env`, `.pem`, `.key`, `.p12`, and `.pfx` are denied unless the root explicitly sets `allowSensitive=true`.
7. `local.fs.write`, `mkdir`, and `copy` require human confirmation in the Runtime. `move` and `delete` are high-risk actions and require approval.
8. Go reserves the `local.fs.*` namespace. Users cannot create lookalike tools or weaken the official risk contract. Existing official tools can be disabled, but their protocol/schema/risk settings are repaired on update/seed.
9. Approval fingerprints bind the exact Tool configuration and arguments. A changed path/action cannot reuse an earlier approval.
10. Desktop Bridge audit logs record successful and denied/failed operation metadata (operation/path/result/error type) only. Tokens and file contents are never intentionally logged.
11. The authorized root itself cannot be deleted or moved. Replacing an existing destination through copy/move requires the corresponding destructive permission.
12. Phase 1 does not expose PowerShell, arbitrary process execution, registry access, browser credentials, or GUI automation.
