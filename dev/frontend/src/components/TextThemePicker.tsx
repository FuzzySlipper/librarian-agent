import React from "react";
import Overlay from "./Overlay";
import { TEXT_THEMES, getTheme, setTheme, type TextTheme } from "../textTheme";

interface TextThemePickerProps {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}

function Swatch({ color, label }: { color: string; label: string }) {
  const isInherit = color === "inherit";
  return (
    <div className="flex items-center gap-1.5">
      <span
        className="inline-block w-3 h-3 rounded-sm ring-1 ring-border/50"
        style={{ backgroundColor: isInherit ? "#888" : color }}
      />
      <span className="text-[10px] text-text-muted">{label}</span>
    </div>
  );
}

const PREVIEW = `She stepped closer. "Are you sure about this?" she whispered.

*The wind howled through the broken windows, carrying dust and memories.*

**He turned sharply**, jaw clenched. "Absolutely," he said.

> The old prophecy spoke of a convergence — a moment when all paths would align.`;

export default function TextThemePicker({ open, onClose, onChanged }: TextThemePickerProps) {
  const active = getTheme().name;

  function handleSelect(theme: TextTheme) {
    setTheme(theme.name);
    onChanged();
  }

  return (
    <Overlay open={open} onClose={onClose} title="Text Theme">
      <div className="flex flex-col gap-3">
        <p className="text-xs text-text-muted">
          Colors quoted dialogue, italic narration, bold text, and blockquotes in chat messages.
        </p>

        <div className="flex flex-col gap-2">
          {TEXT_THEMES.map((theme) => (
            <button
              key={theme.name}
              onClick={() => handleSelect(theme)}
              className={`flex items-center justify-between px-3 py-2.5 rounded-lg text-left transition-colors ${
                theme.name === active
                  ? "bg-accent/20 ring-1 ring-accent/50"
                  : "hover:bg-input-bg"
              }`}
            >
              <div className="flex flex-col gap-1">
                <span className={`text-sm font-medium ${theme.name === active ? "text-accent" : "text-text"}`}>
                  {theme.name}
                </span>
                <div className="flex gap-3">
                  <Swatch color={theme.quote} label="quotes" />
                  <Swatch color={theme.em} label="italic" />
                  <Swatch color={theme.strong} label="bold" />
                  <Swatch color={theme.blockquote} label="blockquote" />
                </div>
              </div>
              {theme.name === active && (
                <span className="text-xs text-accent/70">active</span>
              )}
            </button>
          ))}
        </div>

        {/* Live preview */}
        <div className="mt-2">
          <div className="text-xs text-text-muted uppercase tracking-wider mb-1.5">Preview</div>
          <div className="rounded-lg bg-surface px-4 py-3 prose prose-invert prose-sm prose-themed max-w-none [&_p]:mb-2 [&_p:last-child]:mb-0">
            {PREVIEW.split("\n\n").map((block, i) => {
              if (block.startsWith("> ")) {
                return <blockquote key={i}><p>{block.slice(2)}</p></blockquote>;
              }
              // Render inline formatting
              const rendered = renderBlock(block);
              return <p key={i}>{rendered}</p>;
            })}
          </div>
        </div>
      </div>
    </Overlay>
  );
}

/** Simple inline markdown rendering for the preview block. */
function renderBlock(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  // Match bold (**...**), italic (*...*), and "quotes"
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|"[^"]*"|\u201c[^\u201d]*\u201d)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const m = match[0];
    if (m.startsWith("**")) {
      parts.push(<strong key={key++}>{m.slice(2, -2)}</strong>);
    } else if (m.startsWith("*")) {
      parts.push(<em key={key++}>{m.slice(1, -1)}</em>);
    } else {
      parts.push(<span key={key++} className="dialogue">{m}</span>);
    }
    last = match.index + m.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
