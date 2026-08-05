"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { formatCell } from "@/lib/format";

const MAX_ROWS = 200;

export function DataTable({ rows }: { rows: Record<string, unknown>[] }) {
  const [open, setOpen] = useState(false);
  const columns = Object.keys(rows[0] ?? {});
  const visibleRows = rows.slice(0, MAX_ROWS);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex items-center gap-1.5 text-xs font-medium text-text-secondary hover:text-foreground">
        <ChevronRight
          className={`size-3.5 transition-transform duration-220 ${open ? "rotate-90" : ""}`}
        />
        Data ({rows.length} row{rows.length === 1 ? "" : "s"})
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0">
        <div className="mt-2 max-h-80 overflow-auto rounded-md border border-border">
          <table className="w-full min-w-max text-left text-xs">
            <thead className="sticky top-0 bg-surface">
              <tr>
                {columns.map((column, i) => (
                  <th
                    key={column}
                    className={`whitespace-nowrap px-3 py-2 font-medium text-text-secondary ${
                      i === 0 ? "sticky left-0 bg-surface" : ""
                    }`}
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-t border-border">
                  {columns.map((column, i) => (
                    <td
                      key={column}
                      className={`whitespace-nowrap px-3 py-2 tabular-nums ${
                        i === 0 ? "sticky left-0 bg-background" : ""
                      }`}
                    >
                      {formatCell(row[column])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > MAX_ROWS ? (
            <p className="border-t border-border px-3 py-2 text-xs text-text-tertiary">
              Showing the first {MAX_ROWS} of {rows.length} rows.
            </p>
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
