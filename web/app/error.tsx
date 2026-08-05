"use client";

import { FatalError } from "@/components/FatalError";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return <FatalError onReset={reset} />;
}
