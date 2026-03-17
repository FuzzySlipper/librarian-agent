import { useRef, useState } from "react";

interface InputBarProps {
  onSend: (text: string) => void;
  disabled: boolean;
}

export default function InputBar({ onSend, disabled }: InputBarProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function handleSend() {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
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
  }

  return (
    <div className="flex gap-2 p-3 bg-surface border-t border-border shrink-0">
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          handleInput();
        }}
        onKeyDown={handleKeyDown}
        placeholder="Say something..."
        rows={1}
        autoFocus
        className="flex-1 bg-input-bg text-text border border-border rounded-lg px-3 py-2.5 text-[15px] resize-none min-h-[44px] max-h-[120px] leading-snug focus:outline-none focus:border-accent"
      />
      <button
        onClick={handleSend}
        disabled={disabled || !text.trim()}
        className="bg-accent hover:bg-accent-hover text-white font-semibold rounded-lg px-4 min-h-[44px] text-[15px] disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
      >
        Send
      </button>
    </div>
  );
}
