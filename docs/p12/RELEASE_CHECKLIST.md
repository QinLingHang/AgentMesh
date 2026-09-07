# AgentMesh v1.0 Release Checklist

## A. Automated release gates

- [ ] P1–P11 regression PASS
- [ ] Go full gate PASS
- [ ] Python full gate PASS
- [ ] React contract tests PASS
- [ ] React production build PASS
- [ ] P11 real-browser E2E PASS
- [ ] P11 bundle gate PASS (<500 kB per JavaScript chunk)
- [ ] P10 production-config regression PASS
- [ ] P12 release validator PASS
- [ ] Codex modified no production files during validation

## B. Release integrity

- [ ] `VERSION` = `1.0.0-rc.1` before manual acceptance
- [ ] `MANIFEST.json` has the same candidate version
- [ ] web package and lockfile have the same candidate version
- [ ] required P12 documents exist
- [ ] clean staging passes `validate-release.py --strict-tree`
- [ ] source archive contains no raw `.env`
- [ ] source archive contains no `.venv`, `node_modules`, `dist`, cache or backup data
- [ ] source archive contains no TLS private key / PEM material
- [ ] source archive contains no generated production backup or source backup (`*.bak`)
- [ ] development `.env`/dependencies/build output were not deleted merely to package the release
- [ ] archive can be listed/extracted without corruption

## C. Operational evidence

- [ ] migration lifecycle documented and automated
- [ ] `/livez` and `/readyz` documented
- [ ] production Gateway is the only public application boundary
- [ ] TLS fail-closed mode documented
- [ ] backup and restore runbook documented
- [ ] rollback/restart boundary documented
- [ ] external Docker Hub failure is distinguished from project-controlled failure

## D. Security evidence

- [ ] RBAC and IDOR boundaries documented
- [ ] Project Knowledge vs GLOBAL Knowledge boundary documented
- [ ] user-global Memory boundary documented
- [ ] BYOK encryption/scoped projection documented
- [ ] Audit redaction documented
- [ ] Provider SSRF boundary documented
- [ ] quota/runtime recheck boundary documented

## E. Human acceptance

Execute `docs/p12/FULL_MANUAL_ACCEPTANCE.md` after all automated gates pass.
Only the user performs the final human acceptance.

- [ ] FULL MANUAL ACCEPTANCE: PASS
- [ ] all temporary QA accounts/data handled as documented
- [ ] screenshots/demo evidence captured
- [ ] RC promoted to `1.0.0`
- [ ] final clean archive built
