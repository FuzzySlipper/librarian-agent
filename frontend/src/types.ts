export type Mode = "general" | "writer" | "roleplay" | "forge";

export interface MessageVariant {
  content: string;
  responseType?: string;
  timestamp: number;
  portrait?: string | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  responseType?: string;
  timestamp: number;
  /** Portrait URL for this message (roleplay mode). */
  portrait?: string | null;
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

export interface ProjectList {
  mode: string;
  directory: string;
  projects: string[];
}
