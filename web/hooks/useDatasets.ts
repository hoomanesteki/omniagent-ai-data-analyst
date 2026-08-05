"use client";

import { useCallback, useEffect, useState } from "react";
import { getDatasets } from "@/lib/api";
import type { DatasetSummary } from "@/lib/types";

export type DatasetsStatus = "loading" | "ready" | "unreachable" | "empty";

export function useDatasets() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [status, setStatus] = useState<DatasetsStatus>("loading");
  const [generation, setGeneration] = useState(0);

  const retry = useCallback(() => setGeneration((g) => g + 1), []);

  useEffect(() => {
    let cancelled = false;
    // Resets status back to "loading" on retry() (generation bump) -- a
    // no-op on the very first run since that's already the initial value.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus("loading");

    getDatasets()
      .then((result) => {
        if (cancelled) return;
        setDatasets(result);
        setStatus(result.length === 0 ? "empty" : "ready");
      })
      .catch(() => {
        if (cancelled) return;
        setDatasets([]);
        setStatus("unreachable");
      });

    return () => {
      cancelled = true;
    };
  }, [generation]);

  return { datasets, status, retry };
}
