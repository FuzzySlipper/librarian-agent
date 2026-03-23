/**
 * StoryForge API client — handles SSE streaming for the forge pipeline.
 */

import type { StreamEvent } from "./api";

/**
 * Stream a forge endpoint via SSE, accumulating progress into a visible log.
 */
export async function sendForgeDesignStream(
  project: string,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  return _streamForgeEndpoint(`/api/forge/${encodeURIComponent(project)}/design`, onEvent, signal);
}

export async function sendForgeStream(
  project: string,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  return _streamForgeEndpoint(`/api/forge/${encodeURIComponent(project)}/start`, onEvent, signal);
}

async function _streamForgeEndpoint(
  url: string,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
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
  const progressLog: string[] = [];

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
          const mapped = _mapForgeEvent(currentEventType, data, progressLog);
          onEvent(mapped);
        } catch {
          // Skip malformed data
        }
      }
    }
  }
}

/**
 * Map forge pipeline SSE events into the StreamEvent format.
 * Progress events accumulate into a log that streams as text_delta.
 */
function _mapForgeEvent(
  eventType: string,
  data: Record<string, unknown>,
  progressLog: string[],
): StreamEvent {
  switch (eventType) {
    case "stage": {
      const msg = data.message as string;
      progressLog.push(`**${msg}**`);
      // Send as both status (for the status bar) and text_delta (for the message)
      return { type: "text_delta", data: { text: (progressLog.length > 1 ? "\n" : "") + `**${msg}**\n` } };
    }

    case "progress": {
      const msg = (data.message as string) || `${data.action} ${data.chapter ?? ""}`.trim();
      progressLog.push(`- ${msg}`);
      return { type: "text_delta", data: { text: `- ${msg}\n` } };
    }

    case "chapter": {
      const msg = `${data.chapter} — ${data.status} (${data.word_count} words)`;
      progressLog.push(`- ${msg}`);
      return { type: "text_delta", data: { text: `- ${msg}\n` } };
    }

    case "stats": {
      const msg = `${data.chapters_complete}/${data.chapters_total} chapters, ${Number(data.total_tokens).toLocaleString()} tokens`;
      progressLog.push(`\n*${msg}*`);
      return { type: "text_delta", data: { text: `\n*${msg}*\n` } };
    }

    case "pause":
      return {
        type: "done",
        data: { content: progressLog.join("\n") + `\n\n${data.message}`, response_type: "confirmation" },
      };

    case "complete":
      return {
        type: "done",
        data: {
          content: progressLog.join("\n") + "\n\n" + (
            data.output_path
              ? `StoryForge complete! Output: \`${data.output_path}\``
              : (data.message as string) || "Stage complete."
          ),
          response_type: "confirmation",
        },
      };

    case "error":
      return { type: "error", data: { message: data.message } };

    case "ping":
      return { type: "status", data: { message: "" } };

    default:
      return { type: "status", data: { message: `[${eventType}] ${JSON.stringify(data)}` } };
  }
}
