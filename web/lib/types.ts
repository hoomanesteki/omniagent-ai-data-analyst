import { z } from "zod";

/**
 * Mirrors omniagent/kernel/models.py field-for-field. Schemas are loose
 * (unknown extra keys pass through) so an additive backend change never
 * breaks the UI -- only a missing/wrong-typed field the UI actually reads
 * will fail to parse.
 */

export const DatasetSummarySchema = z.object({
  dataset_id: z.string(),
  label: z.string(),
  description: z.string(),
  starter_questions: z.array(z.string()),
});
export type DatasetSummary = z.infer<typeof DatasetSummarySchema>;

export const MetricValueSchema = z.looseObject({
  metric: z.string(),
  value: z.unknown(),
  formatted: z.string().optional(),
  unit: z.string().nullable().optional(),
  currency: z.string().nullable().optional(),
});
export type MetricValue = z.infer<typeof MetricValueSchema>;

export const DisplayFormatSchema = z.looseObject({
  type: z.enum(["number", "currency", "percent"]),
  precision: z.number().default(2),
  currency: z.string().nullable().optional(),
  good_direction: z.enum(["up", "down"]).nullable().optional(),
});
export type DisplayFormat = z.infer<typeof DisplayFormatSchema>;

export const ChartSpecSchema = z.looseObject({
  mark: z.string(),
  encoding: z.record(z.string(), z.unknown()).default({}),
  title: z.string().default(""),
  subtitle: z.string().default(""),
  formats: z.record(z.string(), DisplayFormatSchema).default({}),
});
export type ChartSpec = z.infer<typeof ChartSpecSchema>;

export const ClarificationSchema = z.looseObject({
  question: z.string(),
  options: z.array(z.string()).optional(),
});
export type Clarification = z.infer<typeof ClarificationSchema>;

export const AnswerEnvelopeKindSchema = z.enum(["answer", "abstention", "clarification"]);
export type AnswerEnvelopeKind = z.infer<typeof AnswerEnvelopeKindSchema>;

export const AnswerEnvelopeSchema = z.looseObject({
  envelope_version: z.string().default("1"),
  kind: AnswerEnvelopeKindSchema,
  headline: z.string().nullable().optional(),
  narration: z.string().nullable().optional(),
  values: z.array(MetricValueSchema).default([]),
  chart: ChartSpecSchema.nullable().optional(),
  rows: z.array(z.record(z.string(), z.unknown())).nullable().optional(),
  table_ref: z.string().nullable().optional(),
  executed_sql: z.string().nullable().optional(),
  metric_request: z.record(z.string(), z.unknown()).nullable().optional(),
  confidence: z.number().nullable().optional(),
  assumptions: z.array(z.string()).default([]),
  suggestions: z.array(z.string()).default([]),
  clarification: ClarificationSchema.nullable().optional(),
  resumable: z.boolean().default(false),
  trace_id: z.string().default(""),
  thread_id: z.string().default(""),
  created_at: z.string().optional(),
});
export type AnswerEnvelope = z.infer<typeof AnswerEnvelopeSchema>;

export const FeedbackResponseSchema = z.looseObject({
  status: z.string(),
  thread_id: z.string(),
  rating: z.enum(["up", "down"]),
  verified_query_created: z.boolean(),
  recorded_at: z.string(),
});
export type FeedbackResponse = z.infer<typeof FeedbackResponseSchema>;

export type FeedbackRating = "up" | "down";

/** One turn in the conversation: the user's question plus the answer it got. */
export type Turn = {
  id: string;
  question: string;
  envelope: AnswerEnvelope;
};
