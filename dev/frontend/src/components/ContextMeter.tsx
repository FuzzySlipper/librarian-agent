import type { Status } from "../types";

interface ContextMeterProps {
  status: Status | null;
}

function fmtTokens(n: number): string {
  if (n >= 1000) return `${Math.round(n / 1000)}k`;
  return `${n}`;
}

export default function ContextMeter({ status }: ContextMeterProps) {
  if (!status || status.status !== "ready") return null;

  const limit = status.context_limit || 128000;
  const lore = status.lore_tokens || 0;
  const persona = status.persona_tokens || 0;
  const history = status.history_tokens || 0;
  const total = lore + persona + history;
  const totalPercent = Math.min((total / limit) * 100, 100);

  // Segment widths as % of the bar
  const loreW = (lore / limit) * 100;
  const personaW = (persona / limit) * 100;
  const historyW = (history / limit) * 100;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-muted">Context usage</span>
        <span className="text-xs text-text-muted">
          {fmtTokens(total)} / {fmtTokens(limit)} ({Math.round(totalPercent)}%)
        </span>
      </div>
      <div className="h-3 rounded-full bg-input-bg overflow-hidden flex">
        {loreW > 0 && (
          <div
            className="h-full bg-blue-500/80"
            style={{ width: `${Math.max(loreW, 0.5)}%` }}
            title={`Lore: ${fmtTokens(lore)} tokens`}
          />
        )}
        {personaW > 0 && (
          <div
            className="h-full bg-purple-500/80"
            style={{ width: `${Math.max(personaW, 0.5)}%` }}
            title={`Persona: ${fmtTokens(persona)} tokens`}
          />
        )}
        {historyW > 0 && (
          <div
            className="h-full bg-accent/80"
            style={{ width: `${Math.max(historyW, 0.5)}%` }}
            title={`Conversation: ${fmtTokens(history)} tokens`}
          />
        )}
      </div>
      <div className="flex gap-4 text-[10px] text-text-muted">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-sm bg-blue-500/80" />
          Lore {fmtTokens(lore)}
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-sm bg-purple-500/80" />
          Persona {fmtTokens(persona)}
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-sm bg-accent/80" />
          Chat {fmtTokens(history)}
        </span>
      </div>
    </div>
  );
}
