export function StarterChips({
  starters,
  disabled,
  onSelect,
}: {
  starters: string[];
  disabled: boolean;
  onSelect: (text: string) => void;
}) {
  if (starters.length === 0) return null;

  return (
    <div className="grid gap-1.5">
      <p className="text-xs font-medium text-text-secondary">Try asking:</p>
      <div className="flex flex-wrap justify-center gap-2">
        {starters.map((question, i) => (
          <button
            key={question}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(question)}
            className="animate-chip-in rounded-full border border-border bg-background px-4 py-2 text-sm transition-colors hover:border-border-strong hover:bg-surface disabled:pointer-events-none disabled:opacity-50"
            style={{ animationDelay: `${i * 40}ms` }}
          >
            {question}
          </button>
        ))}
      </div>
    </div>
  );
}
