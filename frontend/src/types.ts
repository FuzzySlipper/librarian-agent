export type Mode = "general" | "writer" | "roleplay";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  responseType?: string;
  timestamp: number;
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
