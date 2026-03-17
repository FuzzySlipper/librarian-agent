import type { Status } from "../types";

interface ContextMeterProps {
  status: Status | null;
}

export default function ContextMeter({ status }: ContextMeterProps) {
  if (!status || status.status !== "ready") return null;

  // Rough token estimates based on what's loaded
  // In the future, the backend can return actual token counts
  const loreTokens = status.lore_files * 500; // rough avg per lore file
  const maxContext = 200000;
  const lorePercent = Math.min((loreTokens / maxContext) * 100, 100);

  return (
    <div className="flex flex-col gap-1.5">
      <div className="text-xs text-text-muted">Context usage (est.)</div>
      <div className="h-2 rounded-full bg-input-bg overflow-hidden">
        <div
          className="h-full rounded-full bg-accent transition-all"
          style={{ width: `${lorePercent}%` }}
        />
      </div>
      <div className="flex justify-between text-xs text-text-muted">
        <span>{status.lore_files} lore files (~{Math.round(loreTokens / 1000)}k tokens)</span>
        <span>{Math.round(lorePercent)}%</span>
      </div>
    </div>
  );
}
