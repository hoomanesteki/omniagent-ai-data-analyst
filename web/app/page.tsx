"use client";

import { useEffect } from "react";
import { ApiUnreachable } from "@/components/ApiUnreachable";
import { AppShell } from "@/components/AppShell";
import { ChatPanel } from "@/components/ChatPanel";
import { EmptyDatasets } from "@/components/EmptyDatasets";
import { useConversation } from "@/hooks/useConversation";
import { useDatasets } from "@/hooks/useDatasets";

export default function Home() {
  const { datasets, status: datasetsStatus, retry: retryDatasets } = useDatasets();
  const conversation = useConversation();

  useEffect(() => {
    if (datasetsStatus === "ready" && !conversation.datasetId && datasets[0]) {
      conversation.selectDataset(datasets[0].dataset_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetsStatus, datasets]);

  if (datasetsStatus === "loading") {
    return null;
  }

  if (datasetsStatus === "unreachable") {
    return <ApiUnreachable onRetry={retryDatasets} />;
  }

  if (datasetsStatus === "empty") {
    return <EmptyDatasets onRetry={retryDatasets} />;
  }

  if (!conversation.datasetId) {
    return null;
  }

  const currentDataset = datasets.find((d) => d.dataset_id === conversation.datasetId);
  const lastEnvelope = conversation.turns.at(-1)?.envelope;
  const awaitingClarification = Boolean(lastEnvelope?.resumable);

  return (
    <AppShell
      datasets={datasets}
      datasetId={conversation.datasetId}
      hasTurns={conversation.turns.length > 0}
      onSelectDataset={conversation.selectDataset}
      onNewConversation={conversation.newConversation}
    >
      <ChatPanel
        turns={conversation.turns}
        starters={currentDataset?.starter_questions ?? []}
        status={conversation.status}
        pendingQuestion={conversation.status === "sending" ? conversation.pendingQuestion : null}
        errorMessage={conversation.status === "error" ? conversation.errorMessage : null}
        awaitingClarification={awaitingClarification}
        onSubmit={conversation.submit}
        onRetry={conversation.retryLastTurn}
        onDismissError={conversation.dismissError}
      />
    </AppShell>
  );
}
