/**
 * Artifact state manager.
 *
 * Tracks the current artifact for panel display and provides
 * API calls for artifact operations.
 */

import type { StreamEvent } from "./api";

export interface Artifact {
  content: string;
  format: string;
  prompt: string;
}

let currentArtifact: Artifact | null = null;
let onArtifactChange: ((artifact: Artifact | null) => void) | null = null;

export function setOnArtifactChange(cb: (artifact: Artifact | null) => void) {
  onArtifactChange = cb;
}

export function getArtifact(): Artifact | null {
  return currentArtifact;
}

export function setArtifact(artifact: Artifact | null) {
  currentArtifact = artifact;
  onArtifactChange?.(artifact);
}

/**
 * Generate an artifact via streaming endpoint.
 */
export async function generateArtifact(
  prompt: string,
  format: string,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/artifact", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, format }),
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

          // Update local state when artifact is done
          if (currentEvent === "done" && data.content) {
            setArtifact({
              content: data.content,
              format: format,
              prompt: prompt,
            });
          }
        } catch {
          // Skip malformed data
        }
      }
    }
  }
}

/**
 * Clear the current artifact.
 */
export async function clearArtifact(): Promise<void> {
  await fetch("/api/artifact/clear", { method: "POST" });
  setArtifact(null);
}

/**
 * Fetch available artifact format types.
 */
export async function getFormats(): Promise<string[]> {
  const resp = await fetch("/api/artifact/formats");
  if (!resp.ok) return [];
  const data = await resp.json();
  return data.formats;
}

/**
 * Initialize — load current artifact from server if any.
 */
export async function init(): Promise<void> {
  try {
    const resp = await fetch("/api/artifact/current");
    if (resp.ok) {
      const data = await resp.json();
      if (data.artifact) {
        currentArtifact = data.artifact;
        onArtifactChange?.(currentArtifact);
      }
    }
  } catch {
    // Server not available
  }
}
