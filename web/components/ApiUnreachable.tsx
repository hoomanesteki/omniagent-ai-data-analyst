"use client";

import { useState } from "react";
import { Check, Copy, RefreshCw, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { API_BASE_URL } from "@/lib/api";

function CopyableCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(command);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="group flex w-full items-center justify-between gap-3 rounded-md bg-surface-2 px-3 py-2 text-left font-mono text-xs text-foreground transition-colors hover:bg-border"
    >
      <span>{command}</span>
      {copied ? (
        <Check className="size-3.5 shrink-0 text-good" />
      ) : (
        <Copy className="size-3.5 shrink-0 text-text-tertiary group-hover:text-foreground" />
      )}
    </button>
  );
}

export function ApiUnreachable({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-5 p-8 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-danger-bg text-danger">
        <WifiOff className="size-5" />
      </div>
      <div className="max-w-sm space-y-1.5">
        <h2 className="text-lg font-semibold">Can’t reach the OmniAgent API</h2>
        <p className="text-sm text-text-secondary">
          Expected it running at <code className="font-mono text-xs">{API_BASE_URL}</code>. Start
          it, then retry.
        </p>
      </div>
      <div className="grid w-full max-w-sm gap-2">
        <CopyableCommand command="just serve" />
        <CopyableCommand command="python scripts/serve.py" />
      </div>
      <Button onClick={onRetry} variant="outline" className="gap-2">
        <RefreshCw className="size-3.5" />
        Retry
      </Button>
    </div>
  );
}
