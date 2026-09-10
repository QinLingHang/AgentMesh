import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const governance = fs.readFileSync(
  new URL("../src/features/governance/Governance.tsx", import.meta.url),
  "utf8",
);

test("governance reconciles project selection after async project hydration", () => {
  assert.match(governance, /projects\.length\s*===\s*0/);
  assert.match(governance, /currentId\s*=\s*projectId\s*==\s*null\s*\?\s*null\s*:\s*Number\(projectId\)/);
  assert.match(
    governance,
    /projects\.some\(\(project\)\s*=>\s*Number\(project\.id\)\s*===\s*currentId\)/,
  );
  assert.match(governance, /setProjectId\(firstProjectId\)/);
  assert.match(governance, /data-testid="governance-project-picker"/);

  // The old bug returned early whenever projectId was null, so a later
  // projects=[] -> projects=[project] hydration could never select a project.
  assert.doesNotMatch(
    governance,
    /if\s*\(\s*!projectId\s*\|\|\s*projects\.some/,
  );
});

test("governance compares project ids by normalized numeric value", () => {
  assert.match(
    governance,
    /projects\.find\(\(project\)\s*=>\s*Number\(project\.id\)\s*===\s*Number\(projectId\)\)/,
  );
});
