import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import type { Message, Mode } from "../types";

interface MessageBubbleProps {
  message: Message;
  index: number;
  mode?: Mode;
  onEdit?: (id: string, newContent: string) => void;
  onRetry?: (id: string) => void;
  onSwipe?: (id: string, direction: "prev" | "next") => void;
}

export default function MessageBubble({ message, index, mode, onEdit, onRetry, onSwipe }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isProse = message.responseType === "prose" || message.responseType === "prose_pending";
  const isPending = message.responseType === "prose_pending";
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(message.content);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const hasVariants = (message.variants?.length ?? 0) > 1;
  const variantIndex = message.activeVariant ?? 0;
  const variantCount = message.variants?.length ?? 1;

  const showPortrait = mode === "roleplay" && !isUser && message.portrait;

  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus();
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = textareaRef.current.scrollHeight + "px";
    }
  }, [editing]);

  function handleSave() {
    const trimmed = editText.trim();
    if (trimmed && trimmed !== message.content && onEdit) {
      onEdit(message.id, trimmed);
    }
    setEditing(false);
  }

  function handleCancel() {
    setEditText(message.content);
    setEditing(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") handleCancel();
    if (e.key === "Enter" && e.ctrlKey) handleSave();
  }

  const bubbleContent = (
    <div
      className={`group max-w-[85%] sm:max-w-[75%] rounded-xl px-4 py-3 leading-relaxed text-[15px] ${
        isUser
          ? "bg-surface-alt rounded-br-sm"
          : `bg-surface rounded-bl-sm ${isProse ? "border-l-3 border-accent" : ""} ${isPending ? "ring-1 ring-accent/40" : ""}`
      } ${showPortrait ? "max-w-none sm:max-w-none" : ""}`}
      onClick={() => {
        if (!isSystem && onEdit && !editing) setEditing(true);
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {!isUser && message.responseType && message.responseType !== "discussion" && (
            <div className="text-[10px] uppercase tracking-wider text-accent mb-1">
              {isPending ? "pending review" : message.responseType}
            </div>
          )}
        </div>
        <span className="text-[9px] text-text-muted/40 font-mono shrink-0 select-none leading-none pt-0.5">
          {index}
        </span>
      </div>

      {!isUser && message.reasoning && (
        <details className="mb-2">
          <summary className="text-[11px] text-text-muted cursor-pointer hover:text-text select-none">
            reasoning
          </summary>
          <div className="mt-1 px-3 py-2 rounded-lg bg-surface-alt/50 border border-border/30 text-[13px] text-text-muted leading-relaxed max-h-60 overflow-y-auto">
            <pre className="whitespace-pre-wrap font-sans">{message.reasoning}</pre>
          </div>
        </details>
      )}

      {editing ? (
        <div className="flex flex-col gap-2">
          <textarea
            ref={textareaRef}
            value={editText}
            onChange={(e) => {
              setEditText(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = e.target.scrollHeight + "px";
            }}
            onKeyDown={handleKeyDown}
            className="bg-input-bg text-text border border-border rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:border-accent"
          />
          <div className="flex gap-2 justify-end">
            <button
              onClick={handleCancel}
              className="text-xs text-text-muted hover:text-text px-2 py-1"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className="text-xs bg-accent text-white rounded px-3 py-1"
            >
              Save
            </button>
            {onRetry && (
              <button
                onClick={() => { handleSave(); onRetry(message.id); }}
                className="text-xs bg-accent/70 hover:bg-accent text-white rounded px-3 py-1"
              >
                Retry
              </button>
            )}
          </div>
        </div>
      ) : (
        <>
          <div className="prose prose-invert prose-sm max-w-none [&_p]:mb-2 [&_p:last-child]:mb-0">
            <ReactMarkdown>{message.content}</ReactMarkdown>
          </div>

          {hasVariants && onSwipe && (
            <div className="flex items-center justify-center gap-3 mt-2 pt-2 border-t border-border/50">
              <button
                onClick={(e) => { e.stopPropagation(); onSwipe(message.id, "prev"); }}
                disabled={variantIndex === 0}
                className="text-xs text-text-muted hover:text-text disabled:opacity-30 px-1"
              >
                &larr;
              </button>
              <span className="text-[10px] text-text-muted">
                {variantIndex + 1} / {variantCount}
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); onSwipe(message.id, "next"); }}
                disabled={variantIndex === variantCount - 1}
                className="text-xs text-text-muted hover:text-text disabled:opacity-30 px-1"
              >
                &rarr;
              </button>
            </div>
          )}

          {!isSystem && onEdit && (
            <div className="text-[10px] text-text-muted mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
              click to edit
            </div>
          )}
        </>
      )}
    </div>
  );

  // System messages: centered, muted style
  if (isSystem) {
    return (
      <div className="flex justify-center">
        <div className="relative max-w-[90%] sm:max-w-[80%] rounded-lg px-4 py-2.5 text-[13px] text-text-muted bg-surface/50 border border-border/50 font-mono">
          <span className="absolute top-1 right-2 text-[9px] text-text-muted/30 font-mono select-none">
            {index}
          </span>
          <div className="prose prose-invert prose-sm max-w-none [&_p]:mb-1.5 [&_p:last-child]:mb-0 [&_code]:text-accent [&_code]:text-[12px]">
            <ReactMarkdown>{message.content}</ReactMarkdown>
          </div>
        </div>
      </div>
    );
  }

  // Roleplay mode with portrait: IM-style layout
  if (showPortrait) {
    return (
      <div className="flex gap-3 items-start">
        <img
          src={message.portrait!}
          alt=""
          className="w-10 h-10 rounded-full object-cover shrink-0 mt-1 ring-1 ring-border"
        />
        <div className="flex-1 min-w-0">
          {bubbleContent}
        </div>
      </div>
    );
  }

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      {bubbleContent}
    </div>
  );
}
