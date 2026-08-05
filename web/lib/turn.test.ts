import { describe, expect, it } from "vitest";
import { nextRequest } from "@/lib/turn";
import type { AnswerEnvelope } from "@/lib/types";

function envelope(overrides: Partial<AnswerEnvelope>): AnswerEnvelope {
  return {
    envelope_version: "1",
    kind: "answer",
    values: [],
    assumptions: [],
    suggestions: [],
    resumable: false,
    trace_id: "t1",
    thread_id: "th1",
    ...overrides,
  };
}

describe("nextRequest", () => {
  it("starts a new thread with /ask when there is no prior thread", () => {
    const result = nextRequest({
      datasetId: "ecommerce",
      threadId: null,
      lastEnvelope: null,
      question: "gross revenue",
    });
    expect(result).toEqual({
      endpoint: "ask",
      body: { dataset_id: "ecommerce", question: "gross revenue" },
    });
  });

  it("continues via /ask after a normal (non-resumable) answer", () => {
    const result = nextRequest({
      datasetId: "ecommerce",
      threadId: "th1",
      lastEnvelope: envelope({ kind: "answer", resumable: false }),
      question: "and last month?",
    });
    expect(result).toEqual({
      endpoint: "ask",
      body: { dataset_id: "ecommerce", question: "and last month?", thread_id: "th1" },
    });
  });

  it("continues via /ask after a non-resumable clarification (no checkpointer wired)", () => {
    const result = nextRequest({
      datasetId: "ecommerce",
      threadId: "th1",
      lastEnvelope: envelope({
        kind: "clarification",
        resumable: false,
        clarification: { question: "Which metric?", options: ["Revenue", "Orders"] },
      }),
      question: "Revenue",
    });
    expect(result.endpoint).toBe("ask");
  });

  it("routes to /resume after a genuinely paused (resumable) clarification", () => {
    const result = nextRequest({
      datasetId: "ecommerce",
      threadId: "th1",
      lastEnvelope: envelope({
        kind: "clarification",
        resumable: true,
        clarification: { question: "Which time range?" },
      }),
      question: "last quarter",
    });
    expect(result).toEqual({
      endpoint: "resume",
      body: { thread_id: "th1", message: "last quarter" },
    });
  });

  it("routes a suggestion-chip click through /resume when awaiting a resumable clarification", () => {
    const result = nextRequest({
      datasetId: "ecommerce",
      threadId: "th1",
      lastEnvelope: envelope({ kind: "clarification", resumable: true }),
      question: "By region",
    });
    expect(result.endpoint).toBe("resume");
  });

  it("never resumes without an active thread_id, even if resumable were somehow true", () => {
    const result = nextRequest({
      datasetId: "ecommerce",
      threadId: null,
      lastEnvelope: envelope({ kind: "clarification", resumable: true }),
      question: "last quarter",
    });
    expect(result.endpoint).toBe("ask");
  });
});
