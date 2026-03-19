/**
 * Layout system — parses layout MD configs and applies them.
 *
 * Layout MD format:
 *   columns: 10% 80% 10%
 *
 *   [left]
 *   type: chat | image | panel | empty
 *   src: /path/to/image.png    (for image type)
 *   fit: cover | contain        (for image type)
 *   position: center center     (for image type)
 *   label: Panel Title          (for panel type)
 *   placeholder: Help text      (for panel type)
 *
 *   [style]
 *   --color-bg: #1a1a2e
 *   --color-accent: #e94560
 *   ...
 */

export interface PanelConfig {
  name: string;
  type: "chat" | "image" | "panel" | "artifact" | "empty";
  src?: string;
  fit?: string;
  position?: string;
  label?: string;
  placeholder?: string;
}

export interface LayoutConfig {
  name: string;
  columns: string;       // CSS grid-template-columns value
  panels: PanelConfig[];
  styles: Record<string, string>;
}

const DEFAULT_LAYOUT: LayoutConfig = {
  name: "default",
  columns: "100%",
  panels: [{ name: "center", type: "chat" }],
  styles: {},
};

let currentLayout: LayoutConfig = { ...DEFAULT_LAYOUT };
let onLayoutChange: ((layout: LayoutConfig) => void) | null = null;

export function setOnLayoutChange(cb: (layout: LayoutConfig) => void) {
  onLayoutChange = cb;
}

export function getLayout(): LayoutConfig {
  return currentLayout;
}

/**
 * Parse a layout MD string into a LayoutConfig.
 */
export function parseLayout(name: string, content: string): LayoutConfig {
  const lines = content.split("\n");
  let columns = "100%";
  const panels: PanelConfig[] = [];
  const styles: Record<string, string> = {};

  let currentSection: string | null = null;
  let currentPanel: PanelConfig | null = null;

  for (const line of lines) {
    const trimmed = line.trim();

    // Skip empty lines (but don't reset section)
    if (!trimmed) continue;

    // Section headers: [name]
    const sectionMatch = trimmed.match(/^\[(\w+)\]$/);
    if (sectionMatch) {
      // Save previous panel
      if (currentPanel) panels.push(currentPanel);
      currentPanel = null;

      const sectionName = sectionMatch[1].toLowerCase();
      if (sectionName === "style") {
        currentSection = "style";
      } else {
        currentSection = "panel";
        currentPanel = { name: sectionName, type: "empty" };
      }
      continue;
    }

    // Key: value lines
    const kvMatch = trimmed.match(/^([^:]+):\s*(.+)$/);
    if (kvMatch) {
      const key = kvMatch[1].trim().toLowerCase();
      const value = kvMatch[2].trim();

      if (currentSection === null) {
        // Top-level config
        if (key === "columns") {
          columns = value;
        }
      } else if (currentSection === "style") {
        // CSS variable
        styles[kvMatch[1].trim()] = value;
      } else if (currentSection === "panel" && currentPanel) {
        // Panel property
        if (key === "type") {
          currentPanel.type = value as PanelConfig["type"];
        } else if (key === "src") {
          currentPanel.src = value;
        } else if (key === "fit") {
          currentPanel.fit = value;
        } else if (key === "position") {
          currentPanel.position = value;
        } else if (key === "label") {
          currentPanel.label = value;
        } else if (key === "placeholder") {
          currentPanel.placeholder = value;
        }
      }
    }
  }

  // Save last panel
  if (currentPanel) panels.push(currentPanel);

  // If no panels were defined, default to single chat
  if (panels.length === 0) {
    panels.push({ name: "center", type: "chat" });
  }

  return { name, columns, panels, styles };
}

/**
 * Apply a layout's CSS variables to the document.
 */
export function applyStyles(styles: Record<string, string>) {
  const root = document.documentElement;

  // Reset to defaults first (clear any previously applied layout styles)
  const defaults: Record<string, string> = {
    "--color-bg": "#1a1a2e",
    "--color-surface": "#16213e",
    "--color-surface-alt": "#0f3460",
    "--color-text": "#e0e0e0",
    "--color-text-muted": "#888888",
    "--color-accent": "#e94560",
    "--color-accent-hover": "#ff6b81",
    "--color-input-bg": "#222244",
    "--color-border": "#333355",
  };

  // Apply defaults
  for (const [key, value] of Object.entries(defaults)) {
    root.style.setProperty(key, value);
  }

  // Apply layout overrides
  for (const [key, value] of Object.entries(styles)) {
    root.style.setProperty(key, value);
  }
}

/**
 * Fetch and apply a layout by name.
 * If saveAsDefault is true (default), persists the choice to config.yaml.
 */
export async function loadLayout(name: string, saveAsDefault = true): Promise<LayoutConfig> {
  const resp = await fetch(`/api/layouts/${encodeURIComponent(name)}`);
  if (!resp.ok) {
    throw new Error(`Layout '${name}' not found`);
  }

  const data = await resp.json();
  const layout = parseLayout(name, data.content);

  currentLayout = layout;
  applyStyles(layout.styles);
  onLayoutChange?.(layout);

  // Persist as default layout
  if (saveAsDefault) {
    fetch("/api/layout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).catch(() => {}); // Fire and forget
  }

  return layout;
}

/**
 * Fetch the list of available layout names.
 */
export async function listLayouts(): Promise<string[]> {
  const resp = await fetch("/api/layouts");
  if (!resp.ok) return [];
  const data = await resp.json();
  return data.layouts;
}

/**
 * Initialize with the user's configured default layout.
 */
export async function init(defaultName?: string): Promise<void> {
  const name = defaultName || "default";
  try {
    await loadLayout(name, false); // Don't re-save on init
  } catch {
    if (name !== "default") {
      // Configured layout not found, try "default"
      try {
        await loadLayout("default", false);
        return;
      } catch { /* fall through */ }
    }
    // No layout file — use built-in defaults
    currentLayout = { ...DEFAULT_LAYOUT };
  }
}
