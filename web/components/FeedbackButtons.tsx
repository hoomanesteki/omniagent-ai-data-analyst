"use client";

import { useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ApiError, sendFeedback } from "@/lib/api";
import type { FeedbackRating } from "@/lib/types";

type Status = "idle" | "sending" | "up" | "down" | "error";

export function FeedbackButtons({ threadId }: { threadId: string }) {
  const [status, setStatus] = useState<Status>("idle");

  async function rate(rating: FeedbackRating) {
    setStatus("sending");
    try {
      const result = await sendFeedback(threadId, rating);
      setStatus(rating);
      toast.success(
        result.verified_query_created
          ? "Thanks — saved as a verified query."
          : "Thanks — feedback recorded.",
      );
    } catch (err) {
      setStatus("error");
      if (err instanceof ApiError && err.status === 404) {
        toast.error("This conversation expired on the server; start a new one.");
      } else if (err instanceof ApiError && err.status === 422) {
        toast.error("Couldn't record that rating.");
      } else {
        toast.error("Couldn't record feedback.");
      }
    }
  }

  return (
    <div className="flex items-center gap-1" role="group" aria-label="Rate this answer">
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Good answer"
        aria-pressed={status === "up"}
        disabled={status === "sending"}
        onClick={() => rate("up")}
        className={status === "up" ? "text-good" : "text-text-tertiary"}
      >
        <ThumbsUp className="size-3.5" fill={status === "up" ? "currentColor" : "none"} />
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Bad answer"
        aria-pressed={status === "down"}
        disabled={status === "sending"}
        onClick={() => rate("down")}
        className={status === "down" ? "text-danger" : "text-text-tertiary"}
      >
        <ThumbsDown className="size-3.5" fill={status === "down" ? "currentColor" : "none"} />
      </Button>
    </div>
  );
}
