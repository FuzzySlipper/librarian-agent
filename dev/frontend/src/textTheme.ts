/** Prose text color themes — purely cosmetic, persisted in localStorage. */

export interface TextTheme {
  name: string;
  /** Color for quoted dialogue ("text in quotes") */
  quote: string;
  /** Color for italic/emphasis text */
  em: string;
  /** Color for bold text */
  strong: string;
  /** Color for blockquote text (> lines) */
  blockquote: string;
  /** Base prose text color (null = inherit from page theme) */
  base: string | null;
}

export const TEXT_THEMES: TextTheme[] = [
  {
    name: "Default",
    quote: "inherit",
    em: "inherit",
    strong: "inherit",
    blockquote: "inherit",
    base: null,
  },
  {
    name: "Classic",
    quote: "#f1e05a",       // warm yellow for dialogue
    em: "#89b4fa",          // soft blue for narration
    strong: "#f0f0f0",      // bright white
    blockquote: "#a6adc8",  // muted lavender
    base: null,
  },
  {
    name: "Solarized",
    quote: "#b58900",       // solarized yellow
    em: "#2aa198",          // solarized cyan
    strong: "#cb4b16",      // solarized orange
    blockquote: "#6c71c4",  // solarized violet
    base: "#839496",        // solarized base0
  },
  {
    name: "Pastel",
    quote: "#f5c2e7",       // pink
    em: "#a6e3a1",          // green
    strong: "#fab387",      // peach
    blockquote: "#94e2d5",  // teal
    base: null,
  },
  {
    name: "Amber",
    quote: "#ffb86c",       // amber/gold for dialogue
    em: "#8abeb7",          // sage for narration
    strong: "#e0c097",      // warm cream
    blockquote: "#b294bb",  // muted purple
    base: null,
  },
  {
    name: "Monokai",
    quote: "#e6db74",       // monokai yellow
    em: "#ae81ff",          // monokai purple
    strong: "#f92672",      // monokai pink
    blockquote: "#75715e",  // monokai comment
    base: "#f8f8f2",        // monokai fg
  },
];

const STORAGE_KEY = "text-theme";

let _current: TextTheme = TEXT_THEMES[0];
let _onChange: ((t: TextTheme) => void) | null = null;

export function init(): void {
  const saved = localStorage.getItem(STORAGE_KEY);
  const theme = TEXT_THEMES.find((t) => t.name === saved) ?? TEXT_THEMES[0];
  apply(theme);
}

export function getTheme(): TextTheme {
  return _current;
}

export function setTheme(name: string): void {
  const theme = TEXT_THEMES.find((t) => t.name === name);
  if (!theme) return;
  localStorage.setItem(STORAGE_KEY, name);
  apply(theme);
}

export function setOnChange(cb: (t: TextTheme) => void): void {
  _onChange = cb;
}

function apply(theme: TextTheme): void {
  _current = theme;
  const root = document.documentElement;
  root.style.setProperty("--prose-quote", theme.quote);
  root.style.setProperty("--prose-em", theme.em);
  root.style.setProperty("--prose-strong", theme.strong);
  root.style.setProperty("--prose-blockquote", theme.blockquote);
  root.style.setProperty("--prose-base", theme.base ?? "inherit");
  _onChange?.(theme);
}
