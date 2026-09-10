# Codex P12 Validation Contract

## Purpose

This document defines the automated acceptance contract for the original
AgentMesh P12 release-candidate stage. P12 is a release and productization gate,
not a new Agent capability.

Codex acts only as the automated validator:

- run tests and release checks;
- report failures with reproducible evidence;
- do not modify production code to manufacture a PASS;
- do not weaken mandatory assertions;
- do not commit, push or merge;
- do not publish a final release while a mandatory gate is failing.

## Mandatory validation layers

The P12 automated gate covers the cumulative P1-P11 platform plus the P12
release path:

1. Go targeted and full regression.
2. Python targeted and full regression.
3. React contract tests and production build.
4. P11 browser E2E.
5. P12 development-session restore E2E with a real browser and real MySQL.
6. Organization / Project persistence across reload.
7. Release identity and required-document validation.
8. Clean staging and strict-tree validation.
9. Source/archive hygiene and secret/privacy scanning.
10. Release archive integrity.

## Session restore requirements

The browser acceptance must verify:

- register/login works on the configured development origin;
- refresh-cookie authentication survives F5;
- logout survives F5;
- current project data is restored from the backend;
- Governance receives the asynchronously restored project list and selects a
  valid project instead of remaining in an empty initial state;
- Organization data created through the UI remains present after reload;
- tests do not substitute an in-memory fake for the real MySQL persistence
  path.

## Security requirements

A PASS requires:

- no plaintext model/API credentials in release artifacts;
- no private-key or environment-secret material in the source archive;
- authentication/session boundaries remain enforced after refresh;
- project/organization authorization is rechecked server-side;
- release packaging excludes dependency/build/cache/browser-profile material.

## Release promotion rule

`P12 FULL AUTOMATED VALIDATION: PASS` is necessary but not sufficient for final
promotion.

The release may move from RC identity to final `v1.0.0` only after:

```text
P12 FULL AUTOMATED VALIDATION: PASS
AND
FULL MANUAL ACCEPTANCE: PASS
```

Any mandatory failure keeps the result at `FAIL`.
