/**
 * StoryForge API client — handles SSE streaming for the forge pipeline.
 */

import type { StreamEvent } from "./api";

/**
 * Stream the forge pipeline execution via SSE.
 * Maps forge-specific events into the standard StreamEvent format
 * that the App's streamRequest handler understands.
 */
export async function sendForgeStream(
  project: string,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/forge/${encodeURIComponent(project)}/start`, {
    method: "POST",
    signal,
  });

  if (!res.ok) {
    const text = await res.text();
    onEvent({ type: "error", data: { message: `Forge error: ${text}` } });
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    onEvent({ type: "error", data: { message: "No response body" } });
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Parse SSE events from buffer (same pattern as api.ts)
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    let currentEventType = "status";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        currentEventType = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          const mapped = _mapForgeEvent(currentEventType, data);
          onEvent(mapped);
        } catch {
          // Skip malformed data
        }
      }
    }
  }
}

/**
 * Map forge pipeline SSE events into the StreamEvent format
 * used by the App's message display.
 */
function _mapForgeEvent(
  eventType: string,
  data: Record<string, unknown>,
): StreamEvent {
  switch (eventType) {
    case "stage":
      return { type: "status", data: { message: data.message } };

    case "progress":
      return {
        type: "status",
        data: { message: (data.message as string) || `${data.action} ${data.chapter ?? ""}`.trim() },
      };

    case "chapter":
      return {
        type: "status",
        data: { message: `${data.chapter} — ${data.status} (${data.word_count} words)` },
      };

    case "stats":
      return {
        type: "status",
        data: {
          message: `${data.chapters_complete}/${data.chapters_total} chapters, ${Number(data.total_tokens).toLocaleString()} tokens`,
        },
      };

    case "pause":
      return {
        type: "done",
        data: { content: data.message, response_type: "confirmation" },
      };

    case "complete":
      return {
        type: "done",
        data: { content: `StoryForge complete! Output: \`${data.output_path}\``, response_type: "confirmation" },
      };

    case "error":
      return { type: "error", data: { message: data.message } };

    case "ping":
      return { type: "status", data: { message: "" } };

    default:
      return { type: "status", data: { message: `[${eventType}] ${JSON.stringify(data)}` } };
  }
}
