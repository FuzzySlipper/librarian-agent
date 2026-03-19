import { useEffect, useState } from "react";
import Overlay from "./Overlay";
import { listSessions, loadSession, deleteSession, type SessionInfo } from "../api";

interface SessionBrowserProps {
  open: boolean;
  onClose: () => void;
  onLoad: (messages: Array<{ role: string; content: string }>, mode: string) => void;
}

function timeAgo(iso: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function SessionBrowser({ open, onClose, onLoad }: SessionBrowserProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    refresh();
  }, [open]);

  async function refresh() {
    try {
      const data = await listSessions();
      setSessions(data.sessions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions");
    }
  }

  async function handleLoad(id: string) {
    setLoading(true);
    setError(null);
    try {
      const data = await loadSession(id);
      onLoad(data.messages, data.mode);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session");
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete session");
    }
  }

  return (
    <Overlay open={open} onClose={onClose} title="Sessions">
      <div className="flex flex-col gap-2">
        {sessions.length === 0 ? (
          <p className="text-sm text-text-muted">No saved sessions.</p>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className={`flex items-start justify-between gap-2 px-3 py-2.5 rounded-lg bg-input-bg/50 border ${
                s.is_current ? "border-accent/40" : "border-border/50"
              }`}
            >
              <button
                onClick={() => handleLoad(s.id)}
                disabled={loading || s.is_current}
                className="flex-1 min-w-0 text-left disabled:opacity-60"
              >
                <div className="text-sm text-text truncate">{s.name}</div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[10px] uppercase tracking-wider text-accent/70 bg-accent/10 px-1.5 py-0.5 rounded">
                    {s.mode}
                  </span>
                  <span className="text-[11px] text-text-muted">
                    {s.turns} turn{s.turns !== 1 ? "s" : ""}
                  </span>
                  <span className="text-[11px] text-text-muted">
                    {timeAgo(s.updated_at)}
                  </span>
                  {s.is_current && (
                    <span className="text-[10px] text-accent">current</span>
                  )}
                </div>
              </button>
              <button
                onClick={() => handleDelete(s.id)}
                className="text-xs text-text-muted hover:text-red-400 px-2 py-1 rounded bg-surface-alt shrink-0"
                title="Delete session"
              >
                Del
              </button>
            </div>
          ))
        )}
        {error && <p className="text-sm text-red-400">{error}</p>}
      </div>
    </Overlay>
  );
}
