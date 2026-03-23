import { useRef, useState, useEffect } from "react";
import { getCommandNames, getCommandUsage } from "../commands";

interface InputBarProps {
  onSend: (text: string) => void;
  disabled: boolean;
}

const MAX_HISTORY = 50;

// Persist command history in localStorage
function loadHistory(): string[] {
  try {
    return JSON.parse(localStorage.getItem("input-history") || "[]");
  } catch {
    return [];
  }
}

function saveHistory(history: string[]) {
  localStorage.setItem("input-history", JSON.stringify(history.slice(-MAX_HISTORY)));
}

export default function InputBar({ onSend, disabled }: InputBarProps) {
  const [text, setText] = useState("");
  const [history] = useState<string[]>(loadHistory);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [savedText, setSavedText] = useState(""); // text before entering history
  const [hints, setHints] = useState<{ name: string; usage?: string }[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isCommand = text.startsWith("/");

  // Update hints when text changes
  useEffect(() => {
    if (!isCommand || text.includes(" ")) {
      setHints([]);
      return;
    }
    const partial = text.slice(1).toLowerCase();
    if (!partial) {
      // Show all commands
      setHints(getCommandNames().map((n) => ({ name: n, usage: getCommandUsage(n) })));
    } else {
      const matches = getCommandNames()
        .filter((c) => c.startsWith(partial))
        .map((n) => ({ name: n, usage: getCommandUsage(n) }));
      setHints(matches);
    }
  }, [text, isCommand]);

  function handleSend() {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;

    // Add to history
    if (history[history.length - 1] !== trimmed) {
      history.push(trimmed);
      saveHistory(history);
    }
    setHistoryIndex(-1);

    onSend(trimmed);
    setText("");
    setHints([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    // Tab-complete command names
    if (e.key === "Tab" && isCommand && !e.shiftKey) {
      e.preventDefault();
      if (hints.length === 1) {
        setText(`/${hints[0].name} `);
        setHints([]);
      } else if (hints.length > 1) {
        // Complete common prefix
        const partial = text.slice(1).split(/\s/)[0].toLowerCase();
        const match = hints.find((h) => h.name.startsWith(partial));
        if (match) {
          setText(`/${match.name} `);
          setHints([]);
        }
      }
      return;
    }

    // Up arrow — previous history
    if (e.key === "ArrowUp" && !e.shiftKey) {
      const el = textareaRef.current;
      // Only navigate history if cursor is at start or text is single-line
      if (el && (el.selectionStart === 0 || !text.includes("\n"))) {
        e.preventDefault();
        if (historyIndex === -1 && history.length > 0) {
          setSavedText(text);
          setHistoryIndex(history.length - 1);
          setText(history[history.length - 1]);
        } else if (historyIndex > 0) {
          setHistoryIndex(historyIndex - 1);
          setText(history[historyIndex - 1]);
        }
      }
      return;
    }

    // Down arrow — next history / back to current
    if (e.key === "ArrowDown" && !e.shiftKey) {
      const el = textareaRef.current;
      if (el && historyIndex >= 0) {
        e.preventDefault();
        if (historyIndex < history.length - 1) {
          setHistoryIndex(historyIndex + 1);
          setText(history[historyIndex + 1]);
        } else {
          setHistoryIndex(-1);
          setText(savedText);
        }
      }
      return;
    }

    // Escape — clear hints, cancel history navigation
    if (e.key === "Escape") {
      if (hints.length > 0) {
        setHints([]);
      } else if (historyIndex >= 0) {
        setHistoryIndex(-1);
        setText(savedText);
      }
      return;
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleInput() {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 120) + "px";
    }
    // Reset history navigation when typing
    if (historyIndex >= 0) {
      setHistoryIndex(-1);
    }
  }

  function handleHintClick(name: string) {
    setText(`/${name} `);
    setHints([]);
    textareaRef.current?.focus();
  }

  return (
    <div className="relative flex gap-2 p-3 bg-surface border-t border-border shrink-0">
      {/* Command hints dropdown */}
      {hints.length > 0 && (
        <div className="absolute bottom-full left-3 right-3 mb-1 bg-surface border border-border rounded-lg shadow-xl max-h-48 overflow-y-auto z-10">
          {hints.map((h) => (
            <button
              key={h.name}
              onClick={() => handleHintClick(h.name)}
              className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-input-bg transition-colors"
            >
              <span className="text-sm font-mono text-accent">/{h.name}</span>
              {h.usage && (
                <span className="text-xs text-text-muted truncate">{h.usage}</span>
              )}
            </button>
          ))}
        </div>
      )}

      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          handleInput();
        }}
        onKeyDown={handleKeyDown}
        placeholder={isCommand ? "Enter command... (Tab to complete)" : "Say something... (/ for commands, ↑ for history)"}
        rows={1}
        autoFocus
        className={`flex-1 bg-input-bg text-text border rounded-lg px-3 py-2.5 text-[15px] resize-none min-h-[44px] max-h-[120px] leading-snug focus:outline-none ${
          isCommand
            ? "border-accent/60 focus:border-accent font-mono text-[14px]"
            : "border-border focus:border-accent"
        }`}
      />
      <button
        onClick={handleSend}
        disabled={disabled || !text.trim()}
        className={`font-semibold rounded-lg px-4 min-h-[44px] text-[15px] disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0 ${
          isCommand
            ? "bg-accent/80 hover:bg-accent text-white"
            : "bg-accent hover:bg-accent-hover text-white"
        }`}
      >
        {isCommand ? "Run" : "Send"}
      </button>
    </div>
  );
}
