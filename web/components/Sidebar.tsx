"use client";

import { useEffect, useState } from "react";
import { DatasetPicker } from "@/components/DatasetPicker";
import { NewConversationButton } from "@/components/NewConversationButton";
import { HelpDialog } from "@/components/HelpDialog";
import { ThemeToggle } from "@/components/ThemeToggle";
import type { DatasetSummary } from "@/lib/types";

export function Sidebar({
  datasets,
  datasetId,
  hasTurns,
  onSelectDataset,
  onNewConversation,
}: {
  datasets: DatasetSummary[];
  datasetId: string;
  hasTurns: boolean;
  onSelectDataset: (id: string) => void;
  onNewConversation: () => void;
}) {
  const [switchNote, setSwitchNote] = useState<string | null>(null);

  useEffect(() => {
    if (!switchNote) return;
    const timeout = setTimeout(() => setSwitchNote(null), 4000);
    return () => clearTimeout(timeout);
  }, [switchNote]);

  return (
    <aside className="flex h-full w-[280px] shrink-0 flex-col gap-5 border-r border-border bg-sidebar p-4">
      <div className="flex items-center gap-2 px-1">
        <span className="flex size-7 items-center justify-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">
          O
        </span>
        <span className="text-base font-semibold tracking-tight">OmniAgent</span>
      </div>

      <DatasetPicker
        datasets={datasets}
        value={datasetId}
        onChange={(id) => {
          if (id === datasetId) return;
          onSelectDataset(id);
          const next = datasets.find((d) => d.dataset_id === id);
          if (hasTurns && next) setSwitchNote(`Started a new conversation for ${next.label}.`);
        }}
        disabled={datasets.length === 0}
      />
      {switchNote ? (
        <p className="-mt-2 text-xs text-text-tertiary" role="status">
          {switchNote}
        </p>
      ) : null}

      <NewConversationButton hasTurns={hasTurns} onNewConversation={onNewConversation} />

      <div className="mt-auto flex flex-col gap-2 border-t border-border pt-3">
        <HelpDialog />
        <div className="flex items-center justify-between px-1">
          <span className="text-xs text-text-tertiary">Appearance</span>
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}
