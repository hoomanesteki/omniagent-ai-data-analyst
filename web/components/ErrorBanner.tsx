import { RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ErrorBanner({
  message,
  onRetry,
  onDismiss,
}: {
  message: string;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-3 rounded-2xl border border-danger-bg bg-danger-bg px-4 py-3 text-sm text-danger"
    >
      <span>{message}</span>
      <div className="flex items-center gap-1 shrink-0">
        <Button variant="ghost" size="sm" onClick={onRetry} className="gap-1.5 text-danger hover:bg-danger/10">
          <RefreshCw className="size-3.5" />
          Retry
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Dismiss"
          onClick={onDismiss}
          className="text-danger hover:bg-danger/10"
        >
          <X className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}
