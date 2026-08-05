import { AbstentionCard } from "@/components/AbstentionCard";
import { AnswerCard } from "@/components/AnswerCard";
import { ClarificationCard } from "@/components/ClarificationCard";
import { UnknownKindCard } from "@/components/UnknownKindCard";
import type { AnswerEnvelope } from "@/lib/types";

export function TurnCard({
  envelope,
  isLatest,
  onSubmitText,
}: {
  envelope: AnswerEnvelope;
  isLatest: boolean;
  onSubmitText: (text: string) => void;
}) {
  switch (envelope.kind) {
    case "answer":
      return <AnswerCard envelope={envelope} onSubmitText={onSubmitText} />;
    case "clarification":
      return (
        <ClarificationCard
          envelope={envelope}
          onSubmitText={onSubmitText}
          disabled={!isLatest}
        />
      );
    case "abstention":
      return <AbstentionCard envelope={envelope} onSubmitText={onSubmitText} />;
    default:
      return <UnknownKindCard envelope={envelope} />;
  }
}
