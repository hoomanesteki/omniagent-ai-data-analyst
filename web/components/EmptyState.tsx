"use client";

import { useEffect, useState } from "react";
import { MessageCircle, Search, Sparkles } from "lucide-react";
import { StarterChips } from "@/components/StarterChips";
import { readOnboardingState, writeOnboardingState } from "@/lib/onboarding";

const STEPS = [
  { icon: Search, title: "Ask", body: "Type a question, or tap a suggestion below." },
  {
    icon: Sparkles,
    title: "Check",
    body: "Each answer shows its confidence, assumptions, and the exact SQL it ran.",
  },
  {
    icon: MessageCircle,
    title: "Follow up",
    body: "After an answer, “Try next” chips ask the obvious next question in one tap.",
  },
];

export function EmptyState({
  starters,
  disabled,
  onSelect,
}: {
  starters: string[];
  disabled: boolean;
  onSelect: (text: string) => void;
}) {
  const [firstVisit, setFirstVisit] = useState<boolean | null>(null);

  useEffect(() => {
    const seen = readOnboardingState().emptyStateSeen;
    // localStorage is only readable client-side, so this can't be the
    // useState initializer -- the one extra render this causes is the
    // deliberate cost of avoiding an SSR/hydration mismatch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFirstVisit(!seen);
    if (!seen) writeOnboardingState({ emptyStateSeen: true });
  }, []);

  // Avoid a flash of the wrong variant before localStorage is read.
  if (firstVisit === null) return null;

  return (
    <div className="flex h-full flex-col items-center justify-center gap-8 p-6 text-center">
      <div className="max-w-[640px] space-y-6">
        <div className="space-y-2">
          <h1 className="text-[32px] leading-[38px] font-semibold tracking-tight">
            Ask questions about your data.
          </h1>
          <p className="text-[15px] leading-6 text-text-secondary">
            Every answer is checked against the numbers — no guessing.
          </p>
        </div>

        {firstVisit ? (
          <ol className="grid gap-4 sm:grid-cols-3">
            {STEPS.map((step, i) => {
              const Icon = step.icon;
              return (
                <li
                  key={step.title}
                  className="animate-turn-in grid gap-1.5 rounded-xl border border-border bg-card p-4 text-left"
                  style={{ animationDelay: `${i * 60}ms` }}
                >
                  <Icon className="size-4 text-primary" />
                  <p className="text-sm font-medium">{step.title}</p>
                  <p className="text-xs text-text-secondary">{step.body}</p>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="text-sm text-text-tertiary">
            Tap a question to start, or ask your own.
          </p>
        )}

        <StarterChips starters={starters} disabled={disabled} onSelect={onSelect} />
      </div>
    </div>
  );
}
