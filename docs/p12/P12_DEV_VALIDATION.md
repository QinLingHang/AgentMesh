# P12 Development Validation

## Goal

Development validation catches release-candidate defects before the final Codex
full acceptance run.

## Targeted checks

The development gate should run, at minimum:

```text
Go targeted regression
Python targeted regression
React contract tests
React production build
P11 browser E2E
P12 session restore browser E2E
release validator
source hygiene / secret scan
```

## Browser persistence focus

P12 development validation must test a fresh authenticated browser lifecycle:

1. register/login;
2. create a project;
3. create or select an Organization;
4. bind the current project where permitted;
5. reload the browser;
6. verify authentication persists;
7. verify project data is restored;
8. verify Governance reconciles its selected project after the asynchronous
   `/api/projects` response;
9. verify Organization data remains visible;
10. logout and verify logout persists after reload.

## Failure policy

- A reproducible product/test failure is `FAIL`.
- A missing external capability is reported separately as an environment block.
- Environment blocks must not be converted into PASS.
- Tests must not modify production behavior to satisfy themselves.
