import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { DatasetSummary } from "@/lib/types";

export function DatasetPicker({
  datasets,
  value,
  onChange,
  disabled,
}: {
  datasets: DatasetSummary[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  const current = datasets.find((d) => d.dataset_id === value);

  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-text-secondary" id="dataset-label">
        Dataset
      </label>
      <Select
        value={value}
        onValueChange={(next) => {
          if (typeof next === "string") onChange(next);
        }}
        disabled={disabled}
      >
        <SelectTrigger aria-labelledby="dataset-label" className="w-full">
          <SelectValue placeholder="Choose a dataset" />
        </SelectTrigger>
        <SelectContent>
          {datasets.map((dataset) => (
            <SelectItem key={dataset.dataset_id} value={dataset.dataset_id}>
              {dataset.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {current ? <p className="text-xs text-text-tertiary">{current.description}</p> : null}
    </div>
  );
}
