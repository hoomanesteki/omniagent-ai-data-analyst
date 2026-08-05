import { TriangleAlert } from "lucide-react";
import { SuggestionChips } from "@/components/SuggestionChips";
import type { AnswerEnvelope } from "@/lib/types";

export function AbstentionCard({
  envelope,
  onSubmitText,
}: {
  envelope: AnswerEnvelope;
  onSubmitText: (text: string) => void;
}) {
  return (
    <div className="animate-turn-in rounded-2xl border border-caution-border bg-caution-bg p-5 shadow-sm">
      <div className="flex gap-3">
        <TriangleAlert className="mt-0.5 size-5 shrink-0 text-caution" />
        <div className="grid flex-1 gap-3">
          <div>
            <p className="text-sm font-medium text-caution">I couldn’t answer that safely</p>
            <p className="mt-1 text-[15px] leading-6 text-foreground">{envelope.narration}</p>
          </div>
          <SuggestionChips
            suggestions={envelope.suggestions}
            disabled={false}
            onSelect={onSubmitText}
          />
        </div>
      </div>
    </div>
  );
}
