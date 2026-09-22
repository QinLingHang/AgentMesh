// Browser acceptance diagnostics must be observational: no diagnostic failure
// may replace the original E2E assertion, and no DOM/host objects may be
// returned by value across CDP's Runtime.evaluate boundary.
export async function cdpElementExists(cdp, selector) {
  const expression = `Boolean(document.querySelector(${JSON.stringify(selector)}))`;
  const present = await cdp.evaluate(expression);
  if (typeof present !== "boolean") {
    throw new TypeError("CDP element presence probe returned a non-boolean value");
  }
  return present;
}

// `getEvidence` must return a *redacted summary* (booleans/counts/policy
// metadata), never prompts, raw model context, credentials or knowledge text.
// Even a broken CDP session or broken diagnostic logger must not conceal the
// production/test failure being investigated.
export async function reportFailurePreservingPrimary(primaryError, label, getEvidence, log = console.error) {
  try {
    const evidence = await getEvidence();
    log(`${label} safe failure diagnostic ${JSON.stringify(evidence)}`);
  } catch {
    try {
      log(`${label} safe failure diagnostic unavailable; original failure preserved`);
    } catch {
      // Reporting is best-effort; the original assertion is authoritative.
    }
  }
  throw primaryError;
}
