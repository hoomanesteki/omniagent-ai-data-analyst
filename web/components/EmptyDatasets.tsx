import { Database, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export function EmptyDatasets({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-5 p-8 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-surface-2 text-text-secondary">
        <Database className="size-5" />
      </div>
      <div className="max-w-sm space-y-1.5">
        <h2 className="text-lg font-semibold">No datasets loaded</h2>
        <p className="text-sm text-text-secondary">
          The API is running, but no datasets are available yet. Generate the sample data and
          load the warehouse first.
        </p>
      </div>
      <code className="rounded-md bg-surface-2 px-3 py-2 font-mono text-xs">
        python scripts/generate_samples.py &amp;&amp; python scripts/load_warehouse.py
      </code>
      <Button onClick={onRetry} variant="outline" className="gap-2">
        <RefreshCw className="size-3.5" />
        Retry
      </Button>
    </div>
  );
}
