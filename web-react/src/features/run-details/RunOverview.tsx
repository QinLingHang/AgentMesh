import type { RunResult } from "../../types";
import { OverviewMetricGrid } from "./OverviewMetricGrid";
import { RunContextPanel } from "./RunContextPanel";
import { RunHealthPanel } from "./RunHealthPanel";

export function RunOverview({
  result,
}: {
  result: RunResult;
}) {
  return (
    <div className="run-overview-page">
      <OverviewMetricGrid
        result={result}
      />

      <RunHealthPanel
        result={result}
      />

      <RunContextPanel
        result={result}
      />
    </div>
  );
}
