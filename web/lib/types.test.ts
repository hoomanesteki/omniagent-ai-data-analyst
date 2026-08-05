import { describe, expect, it } from "vitest";
import { AnswerEnvelopeSchema, DatasetSummarySchema } from "@/lib/types";

/**
 * Fixtures captured verbatim from a real running omniagent.channels.service
 * app (ScriptedLLM-backed, real DuckDB warehouse) -- not hand-written, so
 * this guards against the TS contract silently drifting from what the
 * Python service actually sends, not just from what this file's own
 * author assumed it sends.
 */

const REAL_DATASETS_RESPONSE = [
  {
    dataset_id: "ecommerce",
    label: "E-commerce",
    description: "Orders, returns, and customers for a direct-to-consumer retailer.",
    starter_questions: ["Average order value", "Customers", "Gross revenue", "Net revenue"],
  },
];

const REAL_SINGLE_KPI_ENVELOPE = {
  envelope_version: "1",
  kind: "answer",
  headline: "Gross revenue was $1,762,252.22.",
  narration: "Gross revenue was $1,762,252.22.",
  values: [
    { metric: "gross_revenue", value: 1762252.2200000058, formatted: "", unit: null, currency: null },
  ],
  chart: null,
  rows: [{ gross_revenue: 1762252.2200000058 }],
  table_ref: null,
  executed_sql:
    "SELECT m0.gross_revenue AS gross_revenue\nFROM (\n  SELECT SUM(orders.order_total) FILTER (WHERE orders.order_status = ?) AS gross_revenue\n  FROM ecommerce_orders AS orders\n) AS m0\nLIMIT 100",
  metric_request: null,
  confidence: 1.0,
  assumptions: [],
  suggestions: ["Gross revenue by Customer country", "Gross revenue by Customer segment", "Average order value"],
  clarification: null,
  resumable: false,
  trace_id: "1685cd49-3594-4d0f-8f2e-2da56d3b2a35",
  thread_id: "91b826ac-3ec4-46c7-b121-d59d32556597",
  created_at: "2026-08-05T03:24:00.540596Z",
};

const REAL_BREAKDOWN_ENVELOPE = {
  envelope_version: "1",
  kind: "answer",
  headline: "Gross revenue breaks down across 10 groups; US leads at $684,015.01.",
  narration: "Gross revenue breaks down across 10 groups; US leads at $684,015.01.",
  values: [],
  chart: {
    mark: "bar",
    encoding: {
      x: { field: "customers__country", type: "nominal", title: "Customer country", sort: "-y" },
      y: { field: "gross_revenue", type: "quantitative", title: "Gross revenue" },
      tooltip: [
        { field: "customers__country", type: "nominal", title: "Customer country" },
        { field: "gross_revenue", type: "quantitative", title: "Gross revenue" },
      ],
    },
    title: "Gross revenue",
    subtitle: "",
    formats: {
      gross_revenue: { type: "currency", precision: 2, currency: "USD", good_direction: "up" },
    },
  },
  rows: [
    { customers__country: "US", gross_revenue: 684015.01 },
    { customers__country: "CA", gross_revenue: 215873.15000000014 },
  ],
  table_ref: null,
  executed_sql: "SELECT m0.customers__country AS customers__country, m0.gross_revenue AS gross_revenue\nFROM (...) AS m0",
  metric_request: null,
  confidence: 1.0,
  assumptions: [],
  suggestions: ["Average order value", "Customers", "Net revenue"],
  clarification: null,
  resumable: false,
  trace_id: "f881470d-fc9b-49cd-b842-0fc856edb8bd",
  thread_id: "7e670707-95ce-4cb5-a561-5e55710a5211",
  created_at: "2026-08-05T03:25:57.176618Z",
};

describe("AnswerEnvelopeSchema against real API responses", () => {
  it("parses a real single-KPI answer", () => {
    const parsed = AnswerEnvelopeSchema.parse(REAL_SINGLE_KPI_ENVELOPE);
    expect(parsed.kind).toBe("answer");
    expect(parsed.values).toHaveLength(1);
    expect(parsed.chart).toBeNull();
  });

  it("parses a real breakdown answer with a chart", () => {
    const parsed = AnswerEnvelopeSchema.parse(REAL_BREAKDOWN_ENVELOPE);
    expect(parsed.kind).toBe("answer");
    expect(parsed.values).toHaveLength(0);
    expect(parsed.chart?.mark).toBe("bar");
    expect(parsed.chart?.formats.gross_revenue?.type).toBe("currency");
  });
});

describe("DatasetSummarySchema against a real API response", () => {
  it("parses the real /datasets response", () => {
    const parsed = DatasetSummarySchema.array().parse(REAL_DATASETS_RESPONSE);
    expect(parsed[0]?.dataset_id).toBe("ecommerce");
    expect(parsed[0]?.starter_questions).toContain("Gross revenue");
  });
});
