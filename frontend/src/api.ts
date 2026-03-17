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
