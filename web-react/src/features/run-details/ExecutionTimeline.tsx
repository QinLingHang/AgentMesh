import type { TraceEvent } from "../../types";
import { prettyTraceDetail } from "../../utils/format";

export function ExecutionTimeline({
  trace,
}: {
  trace: TraceEvent[];
}) {
  return (
    <div className="timeline">
      {trace.map(
        (event, index) => (
          <div
            className={`timeline-item ${event.status}`}
            key={`${event.title}-${index}`}
          >
            <div className="timeline-track">
              <span />
            </div>

            <div className="timeline-body">
              <div className="timeline-header">
                <div>
                  <small>
                    {
                      event.kind
                    }
                  </small>

                  <strong>
                    {
                      event.title
                    }
                  </strong>
                </div>

                <time>
                  {
                    event.elapsedMs
                  }{" "}
                  ms
                </time>
              </div>

              {event.detail && (
                <pre>
                  {prettyTraceDetail(
                    event,
                  )}
                </pre>
              )}
            </div>
          </div>
        ),
      )}
    </div>
  );
}

