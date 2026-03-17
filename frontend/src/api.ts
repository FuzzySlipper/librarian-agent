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
  type: "status" | "tool" | "done" | "error";
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
): Promise<unknown> {
  return request("/api/mode", {
    method: "POST",
    body: JSON.stringify({ mode, project, file }),
  });
}

export async function getProjects(): Promise<ProjectList> {
  return request("/api/projects");
}

export async function newSession(): Promise<unknown> {
  return request("/api/session/new", { method: "POST" });
}

export interface LoreFileInfo {
  path: string;
  tokens: number;
  size: number;
}

export async function listLore(): Promise<{ files: LoreFileInfo[]; lore_path: string }> {
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
