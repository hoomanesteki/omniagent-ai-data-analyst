import { SquarePen } from "lucide-react";
import { Button } from "@/components/ui/button";

export function NewConversationButton({
  hasTurns,
  onNewConversation,
}: {
  hasTurns: boolean;
  onNewConversation: () => void;
}) {
  return (
    <Button
      variant="outline"
      className="w-full justify-start gap-2"
      disabled={!hasTurns}
      onClick={onNewConversation}
    >
      <SquarePen className="size-4" />
      New conversation
    </Button>
  );
}
