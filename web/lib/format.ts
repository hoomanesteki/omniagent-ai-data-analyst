import type { DisplayFormat } from "@/lib/types";

/** The API exposes a metric only by its raw compiled column name (e.g.
 * "gross_revenue" or the qualified/aliased "customers__country") -- there's
 * no separate short display label in the contract, only the full narrated
 * sentence (which duplicates the number). This is a readable stand-in, not
 * a replacement for the catalog's real MetricInfo.label. */
export function humanizeMetricName(name: string): string {
  const last = name.split("__").pop() ?? name;
  return last
    .split("_")
    .filter(Boolean)
    .map((word) => word[0]!.toUpperCase() + word.slice(1))
    .join(" ");
}

/** Formats a single metric value using a backend-declared DisplayFormat
 * when one exists, else a reasonable Intl.NumberFormat default. `value` is
 * `unknown` because the backend types it `Any` -- narrow explicitly rather
 * than trusting it's a number. */
export function formatMetricValue(value: unknown, format?: DisplayFormat | null): string {
  if (value === null || value === undefined) return "—";

  if (typeof value !== "number") {
    return String(value);
  }

  if (!format) {
    return new Intl.NumberFormat("en-US", {
      maximumFractionDigits: Number.isInteger(value) ? 0 : 2,
    }).format(value);
  }

  switch (format.type) {
    case "currency":
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: format.currency ?? "USD",
        minimumFractionDigits: format.precision,
        maximumFractionDigits: format.precision,
      }).format(value);
    case "percent":
      return new Intl.NumberFormat("en-US", {
        style: "percent",
        minimumFractionDigits: format.precision,
        maximumFractionDigits: format.precision,
      }).format(value);
    case "number":
    default:
      return new Intl.NumberFormat("en-US", {
        minimumFractionDigits: 0,
        maximumFractionDigits: format.precision,
      }).format(value);
  }
}

export type ConfidenceLevel = "high" | "medium" | "low";

export function confidenceLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.85) return "high";
  if (confidence >= 0.6) return "medium";
  return "low";
}

export function formatConfidence(confidence: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 0,
  }).format(confidence);
}

/** Compact display for a raw table cell -- unlike formatMetricValue, this
 * has no DisplayFormat to work from, since table rows carry raw column
 * values, not metric-typed ones. */
export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return new Intl.NumberFormat("en-US", {
      maximumFractionDigits: Number.isInteger(value) ? 0 : 2,
    }).format(value);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}
