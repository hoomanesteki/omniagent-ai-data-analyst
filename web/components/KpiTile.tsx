import { formatMetricValue } from "@/lib/format";
import type { DisplayFormat, MetricValue } from "@/lib/types";

export function KpiTile({
  label,
  value,
  format,
}: {
  label: string;
  value: MetricValue;
  format?: DisplayFormat | null;
}) {
  const display = value.formatted && value.formatted.length > 0
    ? value.formatted
    : formatMetricValue(value.value, format);

  return (
    <div>
      <p className="text-sm text-text-secondary">{label}</p>
      <p className="text-[40px] leading-[44px] font-semibold tracking-tight tabular-nums">
        {display}
        {value.unit ? (
          <span className="ml-1.5 text-lg font-medium text-text-secondary">{value.unit}</span>
        ) : null}
      </p>
    </div>
  );
}
