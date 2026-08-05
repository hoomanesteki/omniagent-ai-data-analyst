import { ThinkingIndicator } from "@/components/ThinkingIndicator";
import { TurnCard } from "@/components/TurnCard";
import { UserBubble } from "@/components/UserBubble";
import type { Turn } from "@/lib/types";

export function MessageList({
  turns,
  pendingQuestion,
  onSubmitText,
}: {
  turns: Turn[];
  pendingQuestion: string | null;
  onSubmitText: (text: string) => void;
}) {
  return (
    <div
      id="chat"
      role="log"
      aria-live="polite"
      aria-relevant="additions"
      className="mx-auto flex max-w-[760px] flex-col gap-6 p-4 sm:p-6"
    >
      {turns.map((turn, i) => (
        <div key={turn.id} className="grid gap-3">
          <UserBubble question={turn.question} />
          <TurnCard
            envelope={turn.envelope}
            isLatest={i === turns.length - 1 && !pendingQuestion}
            onSubmitText={onSubmitText}
          />
        </div>
      ))}

      {pendingQuestion ? (
        <div className="grid gap-3">
          <UserBubble question={pendingQuestion} />
          <ThinkingIndicator />
        </div>
      ) : null}
    </div>
  );
}
