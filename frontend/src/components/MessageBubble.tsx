import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import type { Message } from "../types";

interface MessageBubbleProps {
  message: Message;
  onEdit?: (id: string, newContent: string) => void;
}

export default function MessageBubble({ message, onEdit }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isProse = message.responseType === "prose" || message.responseType === "prose_pending";
  const isPending = message.responseType === "prose_pending";
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(message.content);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`group max-w-[85%] sm:max-w-[75%] rounded-xl px-4 py-3 leading-relaxed text-[15px] ${
          isUser
            ? "bg-surface-alt rounded-br-sm"
            : `bg-surface rounded-bl-sm ${isProse ? "border-l-3 border-accent" : ""} ${isPending ? "ring-1 ring-accent/40" : ""}`
        }`}
        onClick={() => {
          if (isUser && onEdit && !editing) setEditing(true);
        }}
      >
        {!isUser && message.responseType && message.responseType !== "discussion" && (
          <div className="text-[10px] uppercase tracking-wider text-accent mb-1">
            {isPending ? "pending review" : message.responseType}
          </div>
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
            </div>
          </div>
        ) : (
          <>
            <div className="prose prose-invert prose-sm max-w-none [&_p]:mb-2 [&_p:last-child]:mb-0">
              <ReactMarkdown>{message.content}</ReactMarkdown>
            </div>
            {isUser && onEdit && (
              <div className="text-[10px] text-text-muted mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                click to edit
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
