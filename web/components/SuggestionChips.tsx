"use client";

import { useEffect, useState } from "react";
import { readOnboardingState, writeOnboardingState } from "@/lib/onboarding";

export function SuggestionChips({
  suggestions,
  disabled,
  onSelect,
}: {
  suggestions: string[];
  disabled: boolean;
  onSelect: (text: string) => void;
}) {
  const [showCoachNote, setShowCoachNote] = useState(false);

  useEffect(() => {
    // localStorage is only readable client-side -- see EmptyState.tsx's
    // identical justification for this pattern.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setShowCoachNote(!readOnboardingState().suggestionsSeen);
  }, []);

  function dismissCoachNote() {
    writeOnboardingState({ suggestionsSeen: true });
    setShowCoachNote(false);
  }

  if (suggestions.length === 0) return null;

  return (
    <div className="grid gap-1.5">
      {showCoachNote ? (
        <p className="text-xs text-text-tertiary">
          <span className="font-medium text-text-secondary">Try next</span> — these are follow-up
          questions built from your data’s catalog. Tap one to ask it.{" "}
          <button
            type="button"
            onClick={dismissCoachNote}
            className="text-primary underline-offset-4 hover:underline"
          >
            Got it
          </button>
        </p>
      ) : (
        <p className="text-xs font-medium text-text-secondary">Try next</p>
      )}
      <div className="flex flex-wrap gap-2">
        {suggestions.map((suggestion, i) => (
          <button
            key={suggestion}
            type="button"
            disabled={disabled}
            onClick={() => {
              dismissCoachNote();
              onSelect(suggestion);
            }}
            className="animate-chip-in rounded-full border border-border bg-background px-4 py-2 text-sm transition-colors hover:border-border-strong hover:bg-surface disabled:pointer-events-none disabled:opacity-50"
            style={{ animationDelay: `${i * 40}ms` }}
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}
