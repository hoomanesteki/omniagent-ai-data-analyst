"use client";

import { useState } from "react";
import { Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sidebar } from "@/components/Sidebar";
import type { DatasetSummary } from "@/lib/types";

export function AppShell({
  datasets,
  datasetId,
  hasTurns,
  onSelectDataset,
  onNewConversation,
  children,
}: {
  datasets: DatasetSummary[];
  datasetId: string;
  hasTurns: boolean;
  onSelectDataset: (id: string) => void;
  onNewConversation: () => void;
  children: React.ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex h-full min-h-0 flex-1">
      {/* Desktop sidebar */}
      <div className="hidden md:block">
        <Sidebar
          datasets={datasets}
          datasetId={datasetId}
          hasTurns={hasTurns}
          onSelectDataset={onSelectDataset}
          onNewConversation={onNewConversation}
        />
      </div>

      {/* Mobile top bar + slide-over sidebar */}
      <div className="flex min-h-0 flex-1 flex-col md:hidden">
        <div className="flex items-center justify-between border-b border-border bg-background px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="flex size-6 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
              O
            </span>
            <span className="text-sm font-semibold">OmniAgent</span>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Open menu"
            onClick={() => setMobileOpen(true)}
          >
            <Menu className="size-4" />
          </Button>
        </div>
        <div className="min-h-0 flex-1">{children}</div>
      </div>

      {/* Desktop content */}
      <div className="hidden min-h-0 flex-1 md:block">{children}</div>

      {mobileOpen ? (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div
            className="absolute inset-0 bg-black/30"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          <div className="relative z-10 h-full w-[280px] animate-in slide-in-from-left duration-200">
            <div className="relative h-full">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Close menu"
                className="absolute top-3 right-3 z-10"
                onClick={() => setMobileOpen(false)}
              >
                <X className="size-4" />
              </Button>
              <Sidebar
                datasets={datasets}
                datasetId={datasetId}
                hasTurns={hasTurns}
                onSelectDataset={(id) => {
                  onSelectDataset(id);
                  setMobileOpen(false);
                }}
                onNewConversation={() => {
                  onNewConversation();
                  setMobileOpen(false);
                }}
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
