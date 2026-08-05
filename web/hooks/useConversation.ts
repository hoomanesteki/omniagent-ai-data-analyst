"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { toast } from "sonner";
import { ApiError, ask, resume } from "@/lib/api";
import { nextRequest } from "@/lib/turn";
import type { AnswerEnvelope, Turn } from "@/lib/types";

type Status = "idle" | "sending" | "error";

type State = {
  datasetId: string | null;
  threadId: string | null;
  turns: Turn[];
  status: Status;
  pendingQuestion: string | null;
  errorMessage: string | null;
};

type Action =
  | { type: "SELECT_DATASET"; datasetId: string }
  | { type: "NEW_CONVERSATION" }
  | { type: "SUBMIT_START"; question: string }
  | { type: "SUBMIT_SUCCESS"; question: string; envelope: AnswerEnvelope }
  | { type: "SUBMIT_ERROR"; message: string }
  | { type: "DISMISS_ERROR" };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "SELECT_DATASET":
      return {
        ...state,
        datasetId: action.datasetId,
        threadId: null,
        turns: [],
        status: "idle",
        pendingQuestion: null,
        errorMessage: null,
      };
    case "NEW_CONVERSATION":
      return { ...state, threadId: null, turns: [], status: "idle", errorMessage: null };
    case "SUBMIT_START":
      return { ...state, status: "sending", pendingQuestion: action.question, errorMessage: null };
    case "SUBMIT_SUCCESS":
      return {
        ...state,
        status: "idle",
        pendingQuestion: null,
        errorMessage: null,
        threadId: action.envelope.thread_id || state.threadId,
        turns: [
          ...state.turns,
          { id: action.envelope.trace_id || crypto.randomUUID(), question: action.question, envelope: action.envelope },
        ],
      };
    case "SUBMIT_ERROR":
      return { ...state, status: "error", errorMessage: action.message };
    case "DISMISS_ERROR":
      return { ...state, status: "idle", pendingQuestion: null, errorMessage: null };
    default:
      return state;
  }
}

const initialState: State = {
  datasetId: null,
  threadId: null,
  turns: [],
  status: "idle",
  pendingQuestion: null,
  errorMessage: null,
};

export function useConversation() {
  const [state, dispatch] = useReducer(reducer, initialState);
  // Mirrors state for use inside submit() without making submit depend on
  // (and re-close over) state each render. Written in an effect, not
  // during render, since submit() is only ever invoked from an event
  // handler after the commit -- by then this effect has already flushed.
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const submit = useCallback(async (question: string) => {
    const current = stateRef.current;
    if (!current.datasetId || !question.trim()) return;

    dispatch({ type: "SUBMIT_START", question });

    const runAsk = () =>
      ask(current.datasetId as string, question, current.threadId);

    const attempt = nextRequest({
      datasetId: current.datasetId,
      threadId: current.threadId,
      lastEnvelope: current.turns.at(-1)?.envelope ?? null,
      question,
    });

    try {
      let envelope: AnswerEnvelope;
      if (attempt.endpoint === "resume") {
        try {
          envelope = await resume(attempt.body.thread_id, attempt.body.message);
        } catch (err) {
          // Self-heal: a stale `resumable` flag (e.g. after an API restart)
          // means there's no pending clarification server-side anymore --
          // fall back to /ask transparently rather than surfacing a 409.
          if (err instanceof ApiError && err.status === 409) {
            envelope = await runAsk();
          } else {
            throw err;
          }
        }
      } else {
        envelope = await runAsk();
      }
      dispatch({ type: "SUBMIT_SUCCESS", question, envelope });
    } catch (err) {
      // Self-heal: the in-memory thread map (service.py's `threads` dict)
      // is lost on an API restart, so an old thread_id 404s -- start a
      // fresh thread with the same question rather than dead-ending.
      if (err instanceof ApiError && err.status === 404 && current.threadId) {
        try {
          const envelope = await ask(current.datasetId, question, null);
          toast.info("Continuing in a new conversation — the previous one expired on the server.");
          dispatch({ type: "SUBMIT_SUCCESS", question, envelope });
          return;
        } catch (retryErr) {
          dispatch({
            type: "SUBMIT_ERROR",
            message: retryErr instanceof ApiError ? retryErr.message : "Something went wrong.",
          });
          return;
        }
      }
      dispatch({
        type: "SUBMIT_ERROR",
        message: err instanceof ApiError ? err.message : "Something went wrong.",
      });
    }
  }, []);

  const selectDataset = useCallback((datasetId: string) => {
    dispatch({ type: "SELECT_DATASET", datasetId });
  }, []);

  const newConversation = useCallback(() => {
    dispatch({ type: "NEW_CONVERSATION" });
  }, []);

  const dismissError = useCallback(() => {
    dispatch({ type: "DISMISS_ERROR" });
  }, []);

  const retryLastTurn = useCallback(() => {
    const question = stateRef.current.pendingQuestion;
    if (question) submit(question);
  }, [submit]);

  return { ...state, submit, selectDataset, newConversation, dismissError, retryLastTurn };
}
