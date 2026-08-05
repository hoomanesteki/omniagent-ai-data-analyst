import { OctagonAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

export function FatalError({ onReset }: { onReset: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <OctagonAlert className="size-8 text-danger" />
      <div className="max-w-sm space-y-1">
        <h2 className="text-lg font-semibold">Something went wrong</h2>
        <p className="text-sm text-text-secondary">
          The app hit an unexpected error rendering this page.
        </p>
      </div>
      <Button onClick={onReset} variant="outline">
        Try again
      </Button>
    </div>
  );
}
