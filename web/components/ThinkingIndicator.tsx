"use client";

import { useEffect, useState } from "react";

export function ThinkingIndicator() {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const timeout = setTimeout(() => setSlow(true), 12_000);
    return () => clearTimeout(timeout);
  }, []);

  return (
    <div
      className="flex items-center gap-2 rounded-2xl border border-border bg-card px-4 py-3 shadow-sm"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <span className="flex gap-1">
        <span className="size-1.5 animate-pulse-dot rounded-full bg-text-tertiary" />
        <span
          className="size-1.5 animate-pulse-dot rounded-full bg-text-tertiary"
          style={{ animationDelay: "160ms" }}
        />
        <span
          className="size-1.5 animate-pulse-dot rounded-full bg-text-tertiary"
          style={{ animationDelay: "320ms" }}
        />
      </span>
      <span className="text-sm text-text-secondary">
        {slow ? "Still working — complex questions take a moment" : "Thinking…"}
      </span>
    </div>
  );
}
