import { MessageCircleQuestion } from "lucide-react";
import type { AnswerEnvelope } from "@/lib/types";

export function ClarificationCard({
  envelope,
  onSubmitText,
  disabled,
}: {
  envelope: AnswerEnvelope;
  onSubmitText: (text: string) => void;
  disabled: boolean;
}) {
  const question = envelope.clarification?.question ?? envelope.narration ?? "";
  const options = envelope.clarification?.options ?? [];

  return (
    <div className="animate-turn-in rounded-2xl border border-primary/20 bg-primary/5 p-5 shadow-sm">
      <div className="flex gap-3">
        <MessageCircleQuestion className="mt-0.5 size-5 shrink-0 text-primary" />
        <div className="grid flex-1 gap-3">
          <p className="text-[15px] leading-6 text-foreground">{question}</p>

          {options.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {options.slice(0, 8).map((option) => (
                <button
                  key={option}
                  type="button"
                  disabled={disabled}
                  onClick={() => onSubmitText(option)}
                  className="rounded-full border border-primary/30 bg-background px-4 py-2 text-sm text-primary transition-colors hover:bg-primary/10 disabled:pointer-events-none disabled:opacity-50"
                >
                  {option}
                </button>
              ))}
            </div>
          ) : null}

          <p className="text-xs text-text-tertiary">
            {options.length > 0 ? "Pick one, or type your own answer." : "Type your answer below."}
          </p>
        </div>
      </div>
    </div>
  );
}
