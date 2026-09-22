// V4.1 QA-only model fixture. Resolve a marker only from a CURRENT retrieved
// evidence body with a matching request-local citation. Never infer an answer
// from a flattened model request, history, image metadata or a guessed [1].
const KINDS = new Set(["PROJECT", "GLOBAL"]);
const EVIDENCE_HEADING = /^\[Evidence ([1-9]\d*)\][ \t]*$/gm;
const RETRIEVED_HEADING = /^\[Retrieved Knowledge\][ \t]*$/gm;
const POLICY_HEADING = /^\[Citation Policy\][ \t]*$/gm;

// The OpenAI-compatible model API accepts both plain strings and content
// parts. Joining text chunks WITHOUT injecting a newline preserves a header,
// citation, or document_id split across two consecutive text parts. Non-text
// parts (including data URLs and metadata) are never searched as evidence.
export function fixtureMessageText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part) => part && typeof part === "object" && part.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("");
}

function headers(text, pattern) {
  return [...text.matchAll(pattern)];
}

function sectionBounds(content) {
  const text = String(content ?? "").replace(/\r\n?/g, "\n");
  const retrievedHeaders = headers(text, RETRIEVED_HEADING);
  if (!retrievedHeaders.length) return { reason: "no_retrieved_section" };
  // Pick the last actual heading, not a first mention in conversation memory or
  // another preceding RAG context. Never combine sections from old messages.
  const latest = retrievedHeaders.at(-1);
  const policies = headers(text, POLICY_HEADING)
    .filter((match) => match.index > latest.index + latest[0].length);
  if (!policies.length) return { reason: "no_citation_policy" };
  const policy = policies[0];
  return {
    retrieved: text.slice(latest.index + latest[0].length, policy.index).trim(),
    policy: text.slice(policy.index + policy[0].length),
    reason: null,
  };
}

function inspectOneMessage(content, kind) {
  const markerPattern = new RegExp(`\\bAGENTMESH_V41_${kind}_[0-9]+\\b`, "i");
  const sections = sectionBounds(content);
  const diagnostic = {
    reason: sections.reason,
    markerInText: markerPattern.test(content),
    markerInRetrieved: false,
    evidenceHeadings: 0,
    allowedCount: 0,
    validIdentityCount: 0,
    citationMismatchCount: 0,
    legacyMismatchCount: 0,
    missingDocumentIdCount: 0,
    markerEvidenceCount: 0,
    markerCitationUnavailableCount: 0,
  };
  if (sections.reason) return { evidence: null, diagnostic };
  const { retrieved, policy } = sections;
  diagnostic.markerInRetrieved = markerPattern.test(retrieved);
  const labels = policy.match(/^available_citations[ \t]*=[ \t]*([^\n]*)$/m)?.[1];
  if (labels === undefined) {
    diagnostic.reason = "no_available_citations_line";
    return { evidence: null, diagnostic };
  }
  const allowed = new Set([...labels.matchAll(/\[([1-9]\d*)\]/g)].map((match) => match[1]));
  diagnostic.allowedCount = allowed.size;
  if (!allowed.size) {
    diagnostic.reason = "empty_available_citations";
    return { evidence: null, diagnostic };
  }
  const headings = headers(retrieved, EVIDENCE_HEADING);
  diagnostic.evidenceHeadings = headings.length;
  if (!headings.length) {
    diagnostic.reason = "no_evidence_headings";
    return { evidence: null, diagnostic };
  }
  for (let index = 0; index < headings.length; index += 1) {
    const heading = headings[index];
    const id = heading[1];
    const start = heading.index + heading[0].length;
    const end = index + 1 < headings.length ? headings[index + 1].index : retrieved.length;
    const block = retrieved.slice(start, end).trim();
    const identityEnd = block.search(/\n[ \t]*\n/);
    if (identityEnd < 0) continue;
    const identity = block.slice(0, identityEnd);
    const evidenceText = block.slice(identityEnd).replace(/^\n[ \t]*\n/, "").trim();
    const declaredId = identity.match(/^citation[ \t]*=[ \t]*\[([1-9]\d*)\][ \t]*$/m)?.[1];
    const legacyId = identity.match(/^\[([1-9]\d*)\][ \t]+source=/m)?.[1];
    const documentId = identity.match(/^document_id[ \t]*=[ \t]*(\S+)[ \t]*$/m)?.[1];
    if (declaredId !== id) { diagnostic.citationMismatchCount += 1; continue; }
    if (legacyId !== id) { diagnostic.legacyMismatchCount += 1; continue; }
    if (!documentId) { diagnostic.missingDocumentIdCount += 1; continue; }
    diagnostic.validIdentityCount += 1;
    const marker = evidenceText.match(markerPattern)?.[0];
    if (!marker) continue;
    diagnostic.markerEvidenceCount += 1;
    if (!allowed.has(id)) {
      diagnostic.markerCitationUnavailableCount += 1;
      continue;
    }
    diagnostic.reason = "valid_evidence";
    return { evidence: { marker, citationId: Number(id) }, diagnostic };
  }
  diagnostic.reason = diagnostic.markerCitationUnavailableCount
    ? "matching_evidence_citation_unavailable"
    : diagnostic.validIdentityCount === 0
      ? "invalid_evidence_identity"
      : diagnostic.markerInRetrieved
        ? "marker_not_in_valid_evidence_body"
        : "marker_outside_retrieved_evidence";
  return { evidence: null, diagnostic };
}

// Safe numeric/boolean/enumerated diagnostics only. Do NOT add source names,
// document IDs, markers, prompt bodies or content excerpts to this output.
export function probeFixtureKnowledgeEvidence(messages, kind) {
  if (!KINDS.has(kind) || !Array.isArray(messages)) {
    return { evidence: null, diagnostic: { reason: "invalid_request" } };
  }
  let userMessages = 0;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role !== "user") continue;
    userMessages += 1;
    const text = fixtureMessageText(message.content);
    if (!text) {
      return { evidence: null, diagnostic: { reason: "empty_latest_user_message", userMessagesInspected: userMessages } };
    }
    // Only the most recent user turn is the current input. Even if that turn
    // contains NO RAG section, a prior turn's evidence must never be replayed
    // into a new answer (including after a scope revocation or user switch).
    const result = inspectOneMessage(text, kind);
    return {
      evidence: result.evidence,
      diagnostic: { ...result.diagnostic, userMessagesInspected: userMessages },
    };
  }
  return {
    evidence: null,
    diagnostic: { reason: "no_retrieved_section", userMessagesInspected: userMessages },
  };
}

export function findFixtureKnowledgeEvidence(messages, kind) {
  return probeFixtureKnowledgeEvidence(messages, kind).evidence;
}

export function groundedFixtureKnowledgeReply(messages) {
  const project = findFixtureKnowledgeEvidence(messages, "PROJECT");
  if (project) {
    return { content: `根据当前项目资料，项目测试标记是 ${project.marker} [${project.citationId}]。` };
  }
  const global = findFixtureKnowledgeEvidence(messages, "GLOBAL");
  if (global) {
    return { content: `根据当前可用资料，测试标记是 ${global.marker} [${global.citationId}]。` };
  }
  return null;
}
