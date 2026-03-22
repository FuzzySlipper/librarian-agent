import { useEffect, useState } from "react";
import Overlay from "./Overlay";
import ContextMeter from "./ContextMeter";
import type { Status } from "../types";

interface ContextOverlayProps {
  open: boolean;
  onClose: () => void;
  status: Status | null;
}

type Tab = "overview" | "debug";

interface HistoryBlock {
  type: string;
  text?: string;
  name?: string;
  input?: Record<string, unknown>;
  tool_use_id?: string;
  content?: string;
}

interface HistoryMessage {
  role: string;
  content?: string;
  length?: number;
  blocks?: HistoryBlock[];
}

export default function ContextOverlay({ open, onClose, status }: ContextOverlayProps) {
  const [tab, setTab] = useState<Tab>("overview");
  const [history, setHistory] = useState<HistoryMessage[]>([]);
  const [historyCount, setHistoryCount] = useState(0);
  const [loadingHistory, setLoadingHistory] = useState(false);

  useEffect(() => {
    if (!open || tab !== "debug") return;
    setLoadingHistory(true);
    fetch("/api/conversation/history")
      .then((r) => r.json())
      .then((data) => {
        setHistory(data.messages ?? []);
        setHistoryCount(data.count ?? 0);
      })
      .catch(() => setHistory([]))
      .finally(() => setLoadingHistory(false));
  }, [open, tab]);

  const tabClass = (t: Tab) =>
    `text-sm px-3 py-1.5 rounded-lg transition-colors ${
      tab === t ? "bg-accent text-white" : "text-text-muted hover:text-text"
    }`;

  return (
    <Overlay open={open} onClose={onClose} title="Context">
      <div className="flex flex-col gap-3">
        <div className="flex gap-2">
          <button onClick={() => setTab("overview")} className={tabClass("overview")}>
            Overview
          </button>
          <button onClick={() => setTab("debug")} className={tabClass("debug")}>
            Debug
          </button>
        </div>

        {tab === "overview" && (
          status?.status === "ready" ? (
            <div className="flex flex-col gap-4">
              <ContextMeter status={status} />
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="bg-input-bg rounded-lg p-3">
                  <div className="text-text-muted text-xs mb-1">Persona</div>
                  <div>{status.persona}</div>
                </div>
                <div className="bg-input-bg rounded-lg p-3">
                  <div className="text-text-muted text-xs mb-1">Lore Set</div>
                  <div>{status.lore_set}</div>
                </div>
                <div className="bg-input-bg rounded-lg p-3">
                  <div className="text-text-muted text-xs mb-1">Writing Style</div>
                  <div>{status.writing_style}</div>
                </div>
                <div className="bg-input-bg rounded-lg p-3">
                  <div className="text-text-muted text-xs mb-1">Model</div>
                  <div className="text-xs break-all">{status.model}</div>
                </div>
                <div className="bg-input-bg rounded-lg p-3">
                  <div className="text-text-muted text-xs mb-1">Conversation</div>
                  <div>{status.conversation_turns} turns</div>
                </div>
                <div className="bg-input-bg rounded-lg p-3">
                  <div className="text-text-muted text-xs mb-1">Lore Files</div>
                  <div>{status.lore_files} loaded</div>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-text-muted">System not ready</p>
          )
        )}

        {tab === "debug" && (
          <div className="flex flex-col gap-2">
            <div className="text-xs text-text-muted">
              {historyCount} messages in backend conversation history
            </div>
            {loadingHistory ? (
              <p className="text-text-muted text-sm">Loading...</p>
            ) : history.length === 0 ? (
              <p className="text-text-muted text-sm">No conversation history.</p>
            ) : (
              <div className="flex flex-col gap-1.5 max-h-[60vh] overflow-y-auto">
                {history.map((msg, i) => (
                  <div
                    key={i}
                    className={`rounded-lg px-3 py-2 text-xs font-mono ${
                      msg.role === "user"
                        ? "bg-surface-alt/70 border-l-2 border-accent/50"
                        : "bg-input-bg/50 border-l-2 border-text-muted/30"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`font-bold ${msg.role === "user" ? "text-accent" : "text-text-muted"}`}>
                        {msg.role}
                      </span>
                      <span className="text-text-muted/50">#{i}</span>
                      {msg.length !== undefined && (
                        <span className="text-text-muted/50">{msg.length} chars</span>
                      )}
                    </div>
                    {msg.content && (
                      <pre className="whitespace-pre-wrap text-text/80 text-[11px] leading-relaxed">
                        {msg.content}
                      </pre>
                    )}
                    {msg.blocks && msg.blocks.map((block, j) => (
                      <div key={j} className="mt-1 pl-2 border-l border-border/50">
                        {block.type === "text" && (
                          <pre className="whitespace-pre-wrap text-text/80 text-[11px]">{block.text}</pre>
                        )}
                        {block.type === "tool_use" && (
                          <div className="text-accent/80">
                            <span className="font-bold">{block.name}</span>
                            <pre className="text-[10px] text-text-muted mt-0.5">
                              {JSON.stringify(block.input, null, 2)}
                            </pre>
                          </div>
                        )}
                        {block.type === "tool_result" && (
                          <div className="text-text-muted/70">
                            <span className="text-[10px]">result:</span>
                            <pre className="text-[10px] mt-0.5">{block.content}</pre>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Overlay>
  );
}
