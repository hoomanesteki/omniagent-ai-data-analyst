import type { VisualizationSpec } from "vega-embed";
import type { ChartSpec } from "@/lib/types";

const KNOWN_MARKS = new Set(["bar", "line", "area", "point", "arc"]);

/** omniagent/agents/charts.py only ever emits "bar" and "line" today, but
 * the contract's `mark` field is a free string (its own comment calls it a
 * "registry key"), so this maps the Vega-Lite-adjacent aliases the backend
 * might reasonably add later and falls back to `null` for anything truly
 * unknown -- callers render a table instead of guessing at a broken chart. */
export function normalizeMark(mark: string): string | null {
  if (KNOWN_MARKS.has(mark)) return mark;
  if (mark === "scatter") return "point";
  if (mark === "pie") return "arc";
  return null;
}

const LIGHT_VL_CONFIG = {
  background: "transparent",
  axis: {
    labelColor: "#6e6e73",
    titleColor: "#1d1d1f",
    domainColor: "#e5e5ea",
    gridColor: "#ebebf0",
    tickColor: "#e5e5ea",
    labelFont: "-apple-system, BlinkMacSystemFont, sans-serif",
    titleFont: "-apple-system, BlinkMacSystemFont, sans-serif",
  },
  legend: {
    labelColor: "#1d1d1f",
    titleColor: "#1d1d1f",
    labelFont: "-apple-system, BlinkMacSystemFont, sans-serif",
    titleFont: "-apple-system, BlinkMacSystemFont, sans-serif",
  },
  title: {
    color: "#1d1d1f",
    font: "-apple-system, BlinkMacSystemFont, sans-serif",
  },
  view: { stroke: "transparent" },
} as const;

const DARK_VL_CONFIG = {
  background: "transparent",
  axis: {
    labelColor: "#a1a1a6",
    titleColor: "#f5f5f7",
    domainColor: "rgba(255,255,255,0.16)",
    gridColor: "rgba(255,255,255,0.10)",
    tickColor: "rgba(255,255,255,0.16)",
    labelFont: "-apple-system, BlinkMacSystemFont, sans-serif",
    titleFont: "-apple-system, BlinkMacSystemFont, sans-serif",
  },
  legend: {
    labelColor: "#f5f5f7",
    titleColor: "#f5f5f7",
    labelFont: "-apple-system, BlinkMacSystemFont, sans-serif",
    titleFont: "-apple-system, BlinkMacSystemFont, sans-serif",
  },
  title: {
    color: "#f5f5f7",
    font: "-apple-system, BlinkMacSystemFont, sans-serif",
  },
  view: { stroke: "transparent" },
} as const;

/** Builds a full Vega-Lite v5 spec from the backend's ChartSpec. The
 * `encoding` object is passed through untouched -- including any
 * `color.scale.range` a grouped-bar chart sets -- so the CVD-safe fixed hue
 * order from charts.py survives in both themes. Only chrome (axis/legend/
 * title text and grid colors) is themed here. */
export function buildVegaSpec(
  chart: ChartSpec,
  rows: Record<string, unknown>[],
  theme: "light" | "dark",
): VisualizationSpec | null {
  const mark = normalizeMark(chart.mark);
  if (!mark) return null;

  const spec: Record<string, unknown> = {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    data: { values: rows },
    mark,
    encoding: chart.encoding,
    width: "container",
    height: 280,
    autosize: { type: "fit", contains: "padding" },
    config: theme === "dark" ? DARK_VL_CONFIG : LIGHT_VL_CONFIG,
  };
  if (chart.title) spec.title = chart.title;
  return spec as VisualizationSpec;
}
