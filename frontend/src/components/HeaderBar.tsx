import type { Status } from "../types";

interface HeaderBarProps {
  status: Status | null;
  onOpenProfile: () => void;
  onOpenMode: () => void;
  onOpenContext: () => void;
  onOpenLore: () => void;
  onNewSession: () => void;
}

export default function HeaderBar({ status, onOpenProfile, onOpenMode, onOpenContext, onOpenLore, onNewSession }: HeaderBarProps) {
  const ready = status?.status === "ready";

  return (
    <header className="flex items-center justify-between px-4 py-3 bg-surface border-b border-border shrink-0">
      <div className="flex items-center gap-3">
        <h1 className="text-base font-semibold">Narrative System</h1>
        {ready && (
          <button
            onClick={onOpenMode}
            className="text-xs px-2 py-1 rounded-md bg-surface-alt text-text-muted hover:text-text transition-colors"
          >
            {status.mode}
            {status.project ? ` / ${status.project}` : ""}
          </button>
        )}
      </div>

      <div className="flex items-center gap-2">
        {ready && (
          <>
            <button
              onClick={onNewSession}
              className="text-xs px-2 py-1 rounded-md bg-surface-alt text-text-muted hover:text-text transition-colors"
              title="Start new session"
            >
              +
            </button>
            <button
              onClick={onOpenLore}
              className="text-xs px-2 py-1 rounded-md bg-surface-alt text-text-muted hover:text-text transition-colors"
              title="Browse lore files"
            >
              {status.lore_files} lore
            </button>
            <button
              onClick={onOpenContext}
              className="text-xs px-2 py-1 rounded-md bg-surface-alt text-text-muted hover:text-text transition-colors"
              title="Context usage"
            >
              ctx
            </button>
            <button
              onClick={onOpenProfile}
              className="text-xs px-2 py-1 rounded-md bg-surface-alt text-text-muted hover:text-text transition-colors"
            >
              {status.persona}
            </button>
          </>
        )}
        {!ready && (
          <span className="text-xs text-text-muted">
            {status ? status.status : "connecting..."}
          </span>
        )}
      </div>
    </header>
  );
}
