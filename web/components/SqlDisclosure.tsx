"use client";

import { useState } from "react";
import { Check, ChevronRight, Copy } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

export function SqlDisclosure({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex items-center gap-1.5 text-xs font-medium text-text-secondary hover:text-foreground">
        <ChevronRight
          className={`size-3.5 transition-transform duration-220 ${open ? "rotate-90" : ""}`}
        />
        Show SQL
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0">
        <div className="relative mt-2 rounded-md bg-surface-2 p-3">
          <button
            type="button"
            aria-label="Copy SQL"
            onClick={async () => {
              await navigator.clipboard.writeText(sql);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
            className="absolute top-2 right-2 rounded-md p-1.5 text-text-tertiary hover:bg-border hover:text-foreground"
          >
            {copied ? <Check className="size-3.5 text-good" /> : <Copy className="size-3.5" />}
          </button>
          <pre className="overflow-x-auto pr-8 font-mono text-[12.5px] leading-5 whitespace-pre-wrap">
            {sql}
          </pre>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
