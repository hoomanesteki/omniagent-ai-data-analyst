"use client";

import { CircleHelp } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { resetOnboardingState } from "@/lib/onboarding";

const STEPS = [
  {
    title: "Ask",
    body: "Type a question, or tap a suggestion below.",
  },
  {
    title: "Check",
    body: "Each answer shows its confidence, assumptions, and the exact SQL it ran.",
  },
  {
    title: "Follow up",
    body: "After an answer, “Try next” chips ask the obvious next question in one tap.",
  },
];

const DETAILS = [
  {
    term: "Confidence",
    body: "How much the answer's own evidence supports it — a full catalog match with no caveats scores highest; a fallback query or a truncated result scores lower.",
  },
  {
    term: "Assumptions",
    body: "Short notes on anything the system had to infer or default, like a time range you didn't specify.",
  },
  {
    term: "Show SQL",
    body: "The exact query that ran against your data, for full transparency — nothing is ever narrated without a query behind it.",
  },
  {
    term: "Clarifying questions",
    body: "If a question is ambiguous, OmniAgent asks before guessing, rather than answering with the wrong number confidently.",
  },
];

export function HelpDialog() {
  return (
    <Dialog>
      <DialogTrigger
        render={
          <Button variant="ghost" size="sm" className="w-full justify-start gap-2 text-text-secondary">
            <CircleHelp className="size-4" />
            How this works
          </Button>
        }
      />
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>How OmniAgent works</DialogTitle>
          <DialogDescription>
            A governed answer engine — every number comes from a real query, checked before it’s
            shown.
          </DialogDescription>
        </DialogHeader>

        <ol className="grid gap-3">
          {STEPS.map((step, i) => (
            <li key={step.title} className="flex gap-3">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                {i + 1}
              </span>
              <div>
                <p className="text-sm font-medium">{step.title}</p>
                <p className="text-sm text-text-secondary">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>

        <dl className="grid gap-2.5 border-t border-border pt-3">
          {DETAILS.map((detail) => (
            <div key={detail.term}>
              <dt className="text-xs font-medium text-text-secondary">{detail.term}</dt>
              <dd className="text-xs text-text-tertiary">{detail.body}</dd>
            </div>
          ))}
        </dl>

        <button
          type="button"
          onClick={() => resetOnboardingState()}
          className="justify-self-start text-xs text-primary underline-offset-4 hover:underline"
        >
          Reset the intro tips
        </button>
      </DialogContent>
    </Dialog>
  );
}
