import {
  AnswerEnvelopeSchema,
  DatasetSummarySchema,
  FeedbackResponseSchema,
  type AnswerEnvelope,
  type DatasetSummary,
  type FeedbackRating,
  type FeedbackResponse,
} from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ApiErrorKind = "network" | "timeout" | "http" | "contract";

export class ApiError extends Error {
  kind: ApiErrorKind;
  status: number | undefined;
  detail: string | undefined;

  constructor(message: string, kind: ApiErrorKind, status?: number, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  schema: { parse: (data: unknown) => T },
  options: { method?: "GET" | "POST"; body?: unknown; timeoutMs?: number } = {},
): Promise<T> {
  const { method = "GET", body, timeoutMs = 10_000 } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (cause) {
    if (controller.signal.aborted) {
      throw new ApiError(`Request to ${path} timed out.`, "timeout");
    }
    throw new ApiError(
      `Can't reach the OmniAgent API at ${API_BASE_URL}.`,
      "network",
      undefined,
      cause instanceof Error ? cause.message : String(cause),
    );
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail;
    } catch {
      // Non-JSON error body -- fall through with no detail.
    }
    throw new ApiError(
      detail ?? `Request to ${path} failed with status ${response.status}.`,
      "http",
      response.status,
      detail,
    );
  }

  const json = await response.json();
  const parsed = schema.parse(json);
  if (parsed === null || parsed === undefined) {
    throw new ApiError(`The API returned an unexpected response from ${path}.`, "contract");
  }
  return parsed;
}

function parseWithContractError<T>(schema: { parse: (data: unknown) => T }, data: unknown): T {
  try {
    return schema.parse(data);
  } catch {
    throw new ApiError("The API returned an unexpected response.", "contract");
  }
}

export async function getHealth(): Promise<{ status: string }> {
  return request("/health", { parse: (d) => d as { status: string } }, { timeoutMs: 5_000 });
}

export async function getDatasets(): Promise<DatasetSummary[]> {
  return request(
    "/datasets",
    { parse: (d) => parseWithContractError(DatasetSummarySchema.array(), d) },
    { timeoutMs: 10_000 },
  );
}

export async function ask(
  datasetId: string,
  question: string,
  threadId: string | null,
): Promise<AnswerEnvelope> {
  const body: Record<string, string> = { dataset_id: datasetId, question };
  if (threadId) body.thread_id = threadId;
  return request(
    "/ask",
    { parse: (d) => parseWithContractError(AnswerEnvelopeSchema, d) },
    { method: "POST", body, timeoutMs: 60_000 },
  );
}

export async function resume(threadId: string, message: string): Promise<AnswerEnvelope> {
  return request(
    "/resume",
    { parse: (d) => parseWithContractError(AnswerEnvelopeSchema, d) },
    { method: "POST", body: { thread_id: threadId, message }, timeoutMs: 60_000 },
  );
}

export async function sendFeedback(
  threadId: string,
  rating: FeedbackRating,
): Promise<FeedbackResponse> {
  return request(
    "/feedback",
    { parse: (d) => parseWithContractError(FeedbackResponseSchema, d) },
    { method: "POST", body: { thread_id: threadId, rating }, timeoutMs: 10_000 },
  );
}

export { API_BASE_URL };
