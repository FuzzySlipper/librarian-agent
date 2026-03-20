export type Mode = "general" | "writer" | "roleplay" | "forge" | "council";

export interface MessageVariant {
  content: string;
  responseType?: string;
  timestamp: number;
  portrait?: string | null;
  reasoning?: string | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  responseType?: string;
  timestamp: number;
  /** Portrait URL for assistant messages (roleplay mode). */
  portrait?: string | null;
  /** Portrait URL for user messages (roleplay mode). */
  userPortrait?: string | null;
  /** Reasoning/thinking content from the model (e.g. DeepSeek reasoning). */
  reasoning?: string | null;
  /** Alternative responses (for swipe). Index 0 is the original. */
  variants?: MessageVariant[];
  /** Currently displayed variant index (0-based). */
  activeVariant?: number;
}

export interface Status {
  status: string;
  mode: Mode;
  project: string | null;
  file: string | null;
  lore_files: number;
  lore_set: string;
  persona: string;
  writing_style: string;
  model: string;
  conversation_turns: number;
  layout: string;
}

export interface Profiles {
  personas: string[];
  lore_sets: string[];
  writing_styles: string[];
  active_persona: string;
  active_lore: string;
  active_writing_style: string;
}

export interface ModeInfo {
  mode: Mode;
  project: string | null;
  file: string | null;
  pending_content: boolean;
}

export interface ProjectEntry {
  name: string;
  files: string[];
}

export interface ProjectList {
  mode: string;
  directory: string;
  projects: ProjectEntry[];
}
