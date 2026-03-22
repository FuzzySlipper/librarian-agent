import type { Status, Profiles, ModeInfo, ProjectList, Mode } from "./types";

const BASE = "";

async function request<T>(
  path: string,
  opts?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export async function getStatus(): Promise<Status> {
  return request("/api/status");
}

export async function sendChat(
  message: string,
): Promise<{ content: string; response_type: string }> {
  return request("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export interface StreamEvent {
  type: "status" | "tool" | "done" | "error" | "text_delta" | "reasoning_delta";
  data: Record<string, unknown>;
}

export async function sendChatStream(
  message: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    signal,
  });

  if (!res.ok) {
    throw new Error(`${res.status}: ${await res.text()}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Parse SSE events from buffer
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    let currentEvent = "status";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent({ type: currentEvent as StreamEvent["type"], data });
        } catch {
          // Skip malformed data
        }
      }
    }
  }
}

export async function sendCouncilStream(
  query: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/council", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
    signal,
  });

  if (!res.ok) {
    throw new Error(`${res.status}: ${await res.text()}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    let currentEvent = "status";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent({ type: currentEvent as StreamEvent["type"], data });
        } catch {
          // Skip malformed data
        }
      }
    }
  }
}

export async function requestImage(
  prompt: string,
): Promise<{ status: string; image_url?: string; error?: string; prompt: string }> {
  return request("/api/imagine", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

export async function getProfiles(): Promise<Profiles> {
  return request("/api/profiles");
}

export async function switchProfile(profile: {
  persona?: string;
  lore_set?: string;
  writing_style?: string;
}): Promise<unknown> {
  return request("/api/profiles/switch", {
    method: "POST",
    body: JSON.stringify(profile),
  });
}

export async function getMode(): Promise<ModeInfo> {
  return request("/api/mode");
}

export async function setMode(
  mode: Mode,
  project?: string,
  file?: string,
  character?: string,
): Promise<unknown> {
  return request("/api/mode", {
    method: "POST",
    body: JSON.stringify({ mode, project, file, character }),
  });
}

export async function getProjects(mode?: string): Promise<ProjectList> {
  const query = mode ? `?mode=${encodeURIComponent(mode)}` : "";
  return request(`/api/projects${query}`);
}

export async function newSession(): Promise<unknown> {
  return request("/api/session/new", { method: "POST" });
}

// ── Session management ──

export interface SessionInfo {
  id: string;
  name: string;
  mode: string;
  turns: number;
  updated_at: string;
  is_current: boolean;
}

export async function listSessions(): Promise<{ sessions: SessionInfo[] }> {
  return request("/api/sessions");
}

export async function loadSession(
  id: string,
): Promise<{ status: string; messages: Array<{ role: string; content: string }>; mode: string }> {
  return request(`/api/sessions/${encodeURIComponent(id)}/load`, { method: "POST" });
}

export async function deleteSession(id: string): Promise<unknown> {
  return request(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
}

// ── Conversation manipulation ──

export async function conversationDelete(index: number): Promise<{ status: string; turns: number }> {
  return request("/api/conversation/delete", {
    method: "POST",
    body: JSON.stringify({ index }),
  });
}

export async function conversationFork(upToIndex: number): Promise<{ status: string; session_id: string; turns: number }> {
  return request("/api/conversation/fork", {
    method: "POST",
    body: JSON.stringify({ up_to_index: upToIndex }),
  });
}

export async function conversationUpdate(index: number, content: string): Promise<{ status: string }> {
  return request("/api/conversation/update", {
    method: "POST",
    body: JSON.stringify({ index, content }),
  });
}

export interface LoreFileInfo {
  path: string;
  tokens: number;
  size: number;
}

export async function listLore(): Promise<{
  files: LoreFileInfo[];
  categories: string[];
  active_project: string | null;
  lore_path: string;
}> {
  return request("/api/lore");
}

export async function readLore(path: string): Promise<{ path: string; content: string; tokens: number }> {
  return request(`/api/lore/${encodeURIComponent(path)}`);
}

export async function writeLore(path: string, content: string): Promise<unknown> {
  return request(`/api/lore/${encodeURIComponent(path)}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export async function deleteLore(path: string): Promise<unknown> {
  return request(`/api/lore/${encodeURIComponent(path)}`, { method: "DELETE" });
}

export async function listLoreProjects(): Promise<{ projects: string[]; active: string }> {
  return request("/api/lore/projects");
}

export async function createLoreProject(name: string): Promise<{ status: string; name: string }> {
  return request("/api/lore/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

// ── Persona / prompt files ──

export interface PersonaFileInfo {
  path: string;
  tokens: number;
  size: number;
}

export async function listPersona(): Promise<{ files: PersonaFileInfo[]; persona_path: string }> {
  return request("/api/persona");
}

export async function readPersona(path: string): Promise<{ path: string; content: string; tokens: number }> {
  return request(`/api/persona/${encodeURIComponent(path)}`);
}

export async function writePersona(path: string, content: string): Promise<unknown> {
  return request(`/api/persona/${encodeURIComponent(path)}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

// ── Writing styles ──

export interface WritingStyleInfo {
  path: string;
  name: string;
  tokens: number;
  size: number;
}

export async function listWritingStyles(): Promise<{ files: WritingStyleInfo[]; active: string }> {
  return request("/api/writing-styles");
}

export async function readWritingStyle(name: string): Promise<{ name: string; content: string; tokens: number }> {
  return request(`/api/writing-styles/${encodeURIComponent(name)}`);
}

export async function writeWritingStyle(name: string, content: string): Promise<unknown> {
  return request(`/api/writing-styles/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

// ── Character cards ──

export interface CharacterCardSummary {
  filename: string;
  name: string;
  portrait: string | null;
}

export interface CharacterCard {
  name: string;
  portrait: string;
  personality: string;
  description: string;
  scenario: string;
  greeting: string;
  _filename?: string;
}

export async function listCharacterCards(): Promise<{
  cards: CharacterCardSummary[];
  active_ai: string | null;
  active_user: string | null;
}> {
  return request("/api/character-cards");
}

export async function readCharacterCard(name: string): Promise<CharacterCard> {
  return request(`/api/character-cards/${encodeURIComponent(name)}`);
}

export async function createCharacterCard(card: Omit<CharacterCard, "_filename">): Promise<{ status: string; filename: string }> {
  return request("/api/character-cards", {
    method: "POST",
    body: JSON.stringify(card),
  });
}

export async function updateCharacterCard(name: string, card: Omit<CharacterCard, "_filename">): Promise<unknown> {
  return request(`/api/character-cards/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify(card),
  });
}

export async function deleteCharacterCard(name: string): Promise<unknown> {
  return request(`/api/character-cards/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export async function activateCharacterCards(config: {
  ai_character?: string | null;
  user_character?: string | null;
}): Promise<unknown> {
  return request("/api/character-cards/activate", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function importCharacterCard(file: File): Promise<{ status: string; card: { filename: string; name: string; portrait?: string } }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch("/api/character-cards/import", {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

// ── Provider management ──

export interface ProviderInfo {
  alias: string;
  name: string;
  type: string;
  base_url: string | null;
  models_url: string | null;
  selected_model: string;
  context_limit?: number;
  api_key_set: boolean;
  used_by?: string[];
  options?: Record<string, unknown> | null;
}

export async function listProviders(): Promise<{ providers: ProviderInfo[] }> {
  return request("/api/providers");
}

export async function createProvider(provider: {
  alias: string;
  name: string;
  type: string;
  base_url?: string | null;
  models_url?: string | null;
  api_key?: string;
  selected_model: string;
  context_limit?: number;
  options?: Record<string, unknown>;
}): Promise<unknown> {
  return request("/api/providers", {
    method: "POST",
    body: JSON.stringify(provider),
  });
}

export async function updateProvider(
  alias: string,
  provider: {
    name?: string;
    type?: string;
    base_url?: string | null;
    models_url?: string | null;
    api_key?: string;
    selected_model?: string;
  },
): Promise<unknown> {
  return request(`/api/providers/${encodeURIComponent(alias)}`, {
    method: "PUT",
    body: JSON.stringify(provider),
  });
}

export async function deleteProvider(alias: string): Promise<unknown> {
  return request(`/api/providers/${encodeURIComponent(alias)}`, {
    method: "DELETE",
  });
}

export async function fetchProviderModels(alias: string): Promise<{ models: string[] }> {
  return request(`/api/providers/${encodeURIComponent(alias)}/models`, {
    method: "POST",
  });
}

export async function fetchModelsForNew(provider: {
  type: string;
  base_url?: string | null;
  models_url?: string | null;
  api_key?: string;
}): Promise<{ models: string[] }> {
  return request("/api/providers/fetch-models", {
    method: "POST",
    body: JSON.stringify(provider),
  });
}

// ── Agent model assignments ──

export interface AgentAssignments {
  orchestrator: string;
  prose_writer: string;
  librarian: string;
}

export async function getAgentModels(): Promise<{ assignments: AgentAssignments }> {
  return request("/api/agents/models");
}

export async function updateAgentModels(
  updates: Partial<AgentAssignments>,
): Promise<{ status: string; assignments: AgentAssignments }> {
  return request("/api/agents/models", {
    method: "PUT",
    body: JSON.stringify(updates),
  });
}
