# P12 Change Manifest

## Scope

P12 converts the validated P1-P11 AgentMesh platform into a reproducible release
candidate. It deliberately avoids adding another major Agent feature.

## Product/session changes

P12 closes development-session and browser-product gaps, including:

- same-origin development API behavior;
- refresh-cookie session restoration after F5;
- authenticated shell recovery;
- project and organization persistence in the real browser flow;
- stable browser selectors that do not depend on accidental localization text.

## Release-system changes

P12 adds or formalizes:

- release identity validation;
- clean temporary staging;
- strict-tree validation;
- Windows/Linux release packaging;
- archive integrity checks;
- forbidden-file and backup-like-file detection;
- secret/privacy scanning;
- required release documentation.

## Required P12 documentation

The release documentation set includes:

- `FINAL_RELEASE.md`
- `RELEASE_CHECKLIST.md`
- `FULL_MANUAL_ACCEPTANCE.md`
- `SECURITY_BOUNDARIES.md`
- `DEMO_SCRIPT.md`
- `INTERVIEW_GUIDE.md`
- `RESUME_PROJECT.md`
- `CODEX_P12_VALIDATION.md`
- `P12_CHANGE_MANIFEST.md`
- `P12_COMPLETION.md`
- `P12_DEV_VALIDATION.md`
- `P12_VALIDATION_CLOSURE_1.md`
- `P12_FINAL_FULL_ACCEPTANCE_CLOSURE_2.md`

## Source-of-truth note

`MANIFEST.json` remains the machine-verifiable file/size/hash inventory for a
specific release tree. This document describes change categories and does not
replace the machine manifest.
