"use client";

import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import { ChartErrorBoundary } from "@/components/ChartErrorBoundary";
import { DataTable } from "@/components/DataTable";
import { Skeleton } from "@/components/ui/skeleton";
import { buildVegaSpec } from "@/lib/vega";
import type { ChartSpec } from "@/lib/types";

const VegaChart = dynamic(() => import("@/components/VegaChart"), {
  ssr: false,
  loading: () => <Skeleton className="h-[280px] w-full rounded-lg" />,
});

export function ChartBlock({
  chart,
  rows,
}: {
  chart: ChartSpec;
  rows: Record<string, unknown>[];
}) {
  const { resolvedTheme } = useTheme();
  const theme = resolvedTheme === "dark" ? "dark" : "light";
  const spec = buildVegaSpec(chart, rows, theme);

  if (!spec) {
    // An unrecognized mark -- degrade to the raw table rather than
    // rendering nothing or a broken chart.
    return <DataTable rows={rows} />;
  }

  return (
    <ChartErrorBoundary fallback={<DataTable rows={rows} />}>
      <div>
        <VegaChart spec={spec} />
        {chart.subtitle ? (
          <p className="mt-1 text-xs text-text-tertiary">{chart.subtitle}</p>
        ) : null}
      </div>
    </ChartErrorBoundary>
  );
}
