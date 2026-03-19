import { useRef, useState } from "react";
import { getCommandNames } from "../commands";

interface InputBarProps {
  onSend: (text: string) => void;
  disabled: boolean;
}

export default function InputBar({ onSend, disabled }: InputBarProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isCommand = text.startsWith("/");

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
    // Tab-complete command names
    if (e.key === "Tab" && isCommand && !e.shiftKey) {
      e.preventDefault();
      const partial = text.slice(1).split(/\s/)[0].toLowerCase();
      if (partial && !text.includes(" ")) {
        const match = getCommandNames().find((c) => c.startsWith(partial));
        if (match) {
          setText(`/${match} `);
        }
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
        placeholder={isCommand ? "Enter command... (Tab to complete)" : "Say something... (/ for commands)"}
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
