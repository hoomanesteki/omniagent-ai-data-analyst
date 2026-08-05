import { Info } from "lucide-react";

export function AssumptionList({ assumptions }: { assumptions: string[] }) {
  if (assumptions.length === 0) return null;

  return (
    <ul className="grid gap-1">
      {assumptions.map((assumption) => (
        <li key={assumption} className="flex items-start gap-1.5 text-xs text-text-tertiary">
          <Info className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
          <span>{assumption}</span>
        </li>
      ))}
    </ul>
  );
}
