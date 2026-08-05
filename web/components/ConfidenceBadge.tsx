import { confidenceLevel, formatConfidence } from "@/lib/format";

const LEVEL_LABEL = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" };
const LEVEL_CLASS = {
  high: "text-good",
  medium: "text-caution",
  low: "text-danger",
};
const LEVEL_DOT_CLASS = {
  high: "bg-good",
  medium: "bg-caution",
  low: "bg-danger",
};

export function ConfidenceBadge({ confidence }: { confidence: number }) {
  const level = confidenceLevel(confidence);
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${LEVEL_CLASS[level]}`}>
      <span className={`size-1.5 rounded-full ${LEVEL_DOT_CLASS[level]}`} aria-hidden="true" />
      {LEVEL_LABEL[level]} · {formatConfidence(confidence)}
    </span>
  );
}
