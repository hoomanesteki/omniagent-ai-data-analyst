import { AssumptionList } from "@/components/AssumptionList";
import { ChartBlock } from "@/components/ChartBlock";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { DataTable } from "@/components/DataTable";
import { FeedbackButtons } from "@/components/FeedbackButtons";
import { KpiTile } from "@/components/KpiTile";
import { SqlDisclosure } from "@/components/SqlDisclosure";
import { SuggestionChips } from "@/components/SuggestionChips";
import { humanizeMetricName } from "@/lib/format";
import type { AnswerEnvelope } from "@/lib/types";

export function AnswerCard({
  envelope,
  onSubmitText,
}: {
  envelope: AnswerEnvelope;
  onSubmitText: (text: string) => void;
}) {
  const rows = envelope.rows ?? [];
  const isSingleKpi = envelope.values.length === 1 && !envelope.chart;

  return (
    <div className="animate-turn-in rounded-2xl border border-border bg-card p-5 shadow-sm">
      <div className="grid gap-4">
        {isSingleKpi ? (
          // headline and narration are always the same full sentence (see
          // service.py's result_to_envelope) -- for a single number, that
          // sentence just restates the tile below it, so the tile's own
          // label is a humanized metric name instead, not the sentence.
          <KpiTile
            label={humanizeMetricName(envelope.values[0]!.metric)}
            value={envelope.values[0]!}
            format={envelope.chart?.formats?.[envelope.values[0]!.metric]}
          />
        ) : envelope.narration ? (
          <p className="max-w-[68ch] text-xl leading-7 font-semibold tracking-tight whitespace-pre-wrap">
            {envelope.narration}
          </p>
        ) : null}

        {envelope.chart && rows.length > 0 ? (
          <ChartBlock chart={envelope.chart} rows={rows} />
        ) : null}

        {rows.length > 1 ? <DataTable rows={rows} /> : null}

        {envelope.confidence !== null && envelope.confidence !== undefined ? (
          <ConfidenceBadge confidence={envelope.confidence} />
        ) : null}

        <AssumptionList assumptions={envelope.assumptions} />

        {envelope.executed_sql ? <SqlDisclosure sql={envelope.executed_sql} /> : null}

        <div className="flex items-center justify-between gap-4">
          <FeedbackButtons threadId={envelope.thread_id} />
        </div>

        <SuggestionChips
          suggestions={envelope.suggestions}
          disabled={false}
          onSelect={onSubmitText}
        />
      </div>
    </div>
  );
}
