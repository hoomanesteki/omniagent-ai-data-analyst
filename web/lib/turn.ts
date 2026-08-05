import type { AnswerEnvelope } from "@/lib/types";

export type AskBody = { dataset_id: string; question: string; thread_id?: string };
export type ResumeBody = { thread_id: string; message: string };

export type NextRequest =
  | { endpoint: "ask"; body: AskBody }
  | { endpoint: "resume"; body: ResumeBody };

/**
 * The one piece of real conversational logic: whether the next message
 * goes through POST /ask or POST /resume.
 *
 * Rule: use /resume only when there's an active thread AND the previous
 * envelope was a genuinely paused graph run (resumable: true). Everything
 * else -- the first message, a typed follow-up, a starter chip, a
 * suggestion chip, or an option on a non-resumable clarification -- goes
 * through /ask on the current thread_id (omitted entirely on the very
 * first message, since the API starts a new thread when it's absent).
 */
export function nextRequest(args: {
  datasetId: string;
  threadId: string | null;
  lastEnvelope: AnswerEnvelope | null;
  question: string;
}): NextRequest {
  const { datasetId, threadId, lastEnvelope, question } = args;

  if (threadId && lastEnvelope?.resumable) {
    return { endpoint: "resume", body: { thread_id: threadId, message: question } };
  }

  const body: AskBody = { dataset_id: datasetId, question };
  if (threadId) body.thread_id = threadId;
  return { endpoint: "ask", body };
}
