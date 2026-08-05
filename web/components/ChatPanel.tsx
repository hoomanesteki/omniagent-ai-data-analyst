"use client";

import { Composer } from "@/components/Composer";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { MessageList } from "@/components/MessageList";
import { useAutoScroll } from "@/hooks/useAutoScroll";
import type { Turn } from "@/lib/types";

export function ChatPanel({
  turns,
  starters,
  status,
  pendingQuestion,
  errorMessage,
  awaitingClarification,
  onSubmit,
  onRetry,
  onDismissError,
}: {
  turns: Turn[];
  starters: string[];
  status: "idle" | "sending" | "error";
  pendingQuestion: string | null;
  errorMessage: string | null;
  awaitingClarification: boolean;
  onSubmit: (text: string) => void;
  onRetry: () => void;
  onDismissError: () => void;
}) {
  const scrollRef = useAutoScroll(turns.length + (pendingQuestion ? 1 : 0));
  const disabled = status === "sending";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {turns.length === 0 && !pendingQuestion ? (
          <EmptyState starters={starters} disabled={disabled} onSelect={onSubmit} />
        ) : (
          <MessageList
            turns={turns}
            pendingQuestion={pendingQuestion}
            onSubmitText={onSubmit}
          />
        )}
      </div>

      {errorMessage ? (
        <div className="mx-auto w-full max-w-[760px] px-4 pb-2 sm:px-6">
          <ErrorBanner message={errorMessage} onRetry={onRetry} onDismiss={onDismissError} />
        </div>
      ) : null}

      <Composer
        onSubmit={onSubmit}
        disabled={disabled}
        placeholder={
          awaitingClarification
            ? "Answer the question above…"
            : "Ask a question about your data…"
        }
      />
    </div>
  );
}
