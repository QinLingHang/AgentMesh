// Browser evidence probes must be pure DOM-to-JSON operations: never return DOM
// objects, raw answer text, knowledge, document identities or user credentials.
// This same function is exercised against synthetic DOM fixtures in Node and
// serialized into Runtime.evaluate for the real Chrome gate.
export function inspectProjectCitationDom(root, marker, expectedFilename) {
  const assistants = [...root.querySelectorAll('[data-testid="message-assistant"]')];
  const streaming = [...root.querySelectorAll('[data-testid="assistant-streaming-answer"]')];
  const visible = (element) => Boolean(
    element && !element.closest('[hidden], [aria-hidden="true"]') &&
    (typeof element.getClientRects !== 'function' || element.getClientRects().length > 0)
  );
  const rows = assistants
    .filter(row => row.querySelector('.citation-answer-content')?.textContent?.includes(marker))
    .map(row => {
      const answer = row.querySelector('.citation-answer-content');
      const summary = row.querySelector('.citation-sources .citation-source-summary');
      const sources = row.querySelector('.citation-sources');
      const answerButtons = [...(answer?.querySelectorAll('button.citation-marker') ?? [])];
      const sourceLabel = summary?.querySelector('.citation-summary-index')?.textContent?.trim();
      const markerMatchesSource = answerButtons.some(button =>
        visible(button) && /^\[\d+\]$/.test(button.textContent?.trim() ?? '') &&
        button.textContent?.trim() === sourceLabel &&
        button.getAttribute('aria-label')?.includes(expectedFilename)
      );
      const matchingSource = summary?.querySelector('strong')?.textContent?.trim() === expectedFilename;
      return {
        durable: Boolean(row.getAttribute('data-message-id')),
        visible: visible(row),
        hasSource: Boolean(sources),
        sourceVisible: visible(summary),
        sourceFilenameMatches: matchingSource,
        sourceLabelMatchesMarker: markerMatchesSource,
        markerButtonCount: answerButtons.length,
        ready: Boolean(row.getAttribute('data-message-id') && visible(row) && visible(summary) &&
          matchingSource && markerMatchesSource),
      };
    });
  return {
    ready: rows.some(row => row.ready),
    assistantCount: assistants.length,
    streamingCount: streaming.length,
    streamingHasMarker: streaming.some(row => row.querySelector('.citation-answer-content')?.textContent?.includes(marker)),
    matchedAnswerRows: rows.length,
    rows: rows.slice(0, 8),
  };
}

export function projectCitationReadyExpression(marker, expectedFilename) {
  return `(${inspectProjectCitationDom.toString()})(document, ${JSON.stringify(marker)}, ${JSON.stringify(expectedFilename)}).ready`;
}

export function projectCitationDiagnosticExpression(marker, expectedFilename) {
  return `(${inspectProjectCitationDom.toString()})(document, ${JSON.stringify(marker)}, ${JSON.stringify(expectedFilename)})`;
}
