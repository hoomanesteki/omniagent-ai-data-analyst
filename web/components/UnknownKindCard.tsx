import { CircleAlert } from "lucide-react";
import type { AnswerEnvelope } from "@/lib/types";

/** Defensive fallback if the backend ever adds an envelope `kind` this UI
 * doesn't know about yet -- degrades to the raw narration/JSON rather than
 * rendering nothing. */
export function UnknownKindCard({ envelope }: { envelope: AnswerEnvelope }) {
  return (
    <div className="animate-turn-in rounded-2xl border border-border bg-card p-5 shadow-sm">
      <div className="flex gap-3">
        <CircleAlert className="mt-0.5 size-5 shrink-0 text-text-tertiary" />
        <div>
          <p className="text-sm font-medium text-text-secondary">
            Unrecognized response ({envelope.kind})
          </p>
          <p className="mt-1 text-[15px] leading-6 text-foreground">
            {envelope.narration ?? "The API returned a response this version of the app doesn't understand yet."}
          </p>
        </div>
      </div>
    </div>
  );
}
