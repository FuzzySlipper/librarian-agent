import type { Message, Mode, Status } from "./types";
import type { StreamEvent } from "./api";

export interface CommandContext {
  /** Current app status */
  status: Status | null;
  /** Current mode */
  mode: Mode;
  /** All messages (for index-based commands) */
  messages: Message[];
  /** Open UI panels */
  openProfile: () => void;
  openMode: () => void;
  openLore: () => void;
  openContext: () => void;
  /** Actions */
  newSession: () => Promise<void>;
  clearMessages: () => void;
  setMode: (mode: Mode) => Promise<void>;
  refreshStatus: () => void;
  /**
   * Stream a request through an endpoint, showing progress in the UI.
   * Used by commands that need the console→orchestrator pattern.
   */
  streamRequest: (
    fetcher: (onEvent: (event: StreamEvent) => void, signal: AbortSignal) => Promise<void>,
  ) => Promise<void>;
}

export interface CommandResult {
  /** Text to display as a system message. Null means no output. */
  output: string | null;
  /**
   * If true, the command is handling its own streaming output
   * (via ctx.streamRequest) and the caller should not add a system message.
   */
  streaming?: boolean;
}

interface CommandDef {
  description: string;
  usage?: string;
  handler: (args: string, ctx: CommandContext) => Promise<CommandResult> | CommandResult;
}

const commands: Record<string, CommandDef> = {
  help: {
    description: "List available commands",
    handler: () => {
      const lines = Object.entries(commands)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([name, cmd]) => {
          const usage = cmd.usage ? ` ${cmd.usage}` : "";
          return `\`/${name}${usage}\` — ${cmd.description}`;
        });
      return { output: lines.join("\n") };
    },
  },

  status: {
    description: "Show current system status",
    handler: (_, ctx) => {
      if (!ctx.status) return { output: "Not connected." };
      const s = ctx.status;
      const lines = [
        `**Mode:** ${s.mode}`,
        `**Persona:** ${s.persona}`,
        `**Writing style:** ${s.writing_style}`,
        `**Lore set:** ${s.lore_set} (${s.lore_files} files)`,
        `**Model:** ${s.model}`,
        `**Turns:** ${s.conversation_turns}`,
      ];
      if (s.project) lines.push(`**Project:** ${s.project}`);
      if (s.file) lines.push(`**File:** ${s.file}`);
      return { output: lines.join("\n") };
    },
  },

  mode: {
    description: "Switch operating mode",
    usage: "[general|writer|roleplay]",
    handler: async (args, ctx) => {
      const target = args.trim().toLowerCase();
      if (!target) {
        ctx.openMode();
        return { output: null };
      }
      const valid: Mode[] = ["general", "writer", "roleplay"];
      if (!valid.includes(target as Mode)) {
        return { output: `Unknown mode \`${target}\`. Valid modes: ${valid.join(", ")}` };
      }
      await ctx.setMode(target as Mode);
      return { output: `Switched to **${target}** mode.` };
    },
  },

  new: {
    description: "Start a new session",
    handler: async (_, ctx) => {
      await ctx.newSession();
      return { output: "Session cleared." };
    },
  },

  clear: {
    description: "Clear chat messages (keeps server session)",
    handler: (_, ctx) => {
      ctx.clearMessages();
      return { output: null };
    },
  },

  profile: {
    description: "Open profile picker",
    handler: (_, ctx) => {
      ctx.openProfile();
      return { output: null };
    },
  },

  lore: {
    description: "Open lore browser",
    handler: (_, ctx) => {
      ctx.openLore();
      return { output: null };
    },
  },

  layout: {
    description: "Switch UI layout",
    usage: "[name]",
    handler: async (args) => {
      const { loadLayout, listLayouts, getLayout } = await import("./layout");
      const target = args.trim().toLowerCase();

      if (!target) {
        const available = await listLayouts();
        const current = getLayout().name;
        if (available.length === 0) {
          return { output: "No layouts found in `layouts/` directory." };
        }
        const lines = available.map((name) => {
          const marker = name === current ? " **(active)**" : "";
          return `\`${name}\`${marker}`;
        });
        return { output: `Available layouts:\n${lines.join("\n")}` };
      }

      try {
        await loadLayout(target);
        return { output: `Layout switched to **${target}**.` };
      } catch {
        const available = await listLayouts();
        return { output: `Layout \`${target}\` not found. Available: ${available.join(", ")}` };
      }
    },
  },

  context: {
    description: "Show system context",
    handler: (_, ctx) => {
      ctx.openContext();
      return { output: null };
    },
  },

  council: {
    description: "Query the council of AI perspectives",
    usage: "<query>",
    handler: async (args, ctx) => {
      const query = args.trim();
      if (!query) {
        return { output: "Usage: `/council <your question>`" };
      }

      const { sendCouncilStream } = await import("./api");
      await ctx.streamRequest((onEvent, signal) =>
        sendCouncilStream(query, onEvent, signal),
      );
      return { output: null, streaming: true };
    },
  },

  artifact: {
    description: "Generate an in-world artifact",
    usage: "<format> <prompt>",
    handler: async (args, ctx) => {
      const parts = args.trim().split(/\s+/);
      if (parts.length < 2) {
        const { getFormats } = await import("./artifacts");
        const formats = await getFormats();
        return {
          output: `Usage: \`/artifact <format> <prompt>\`\n\nAvailable formats: ${formats.map((f) => `\`${f}\``).join(", ")}`,
        };
      }

      const format = parts[0].toLowerCase();
      const prompt = parts.slice(1).join(" ");

      const { generateArtifact } = await import("./artifacts");
      await ctx.streamRequest((onEvent, signal) =>
        generateArtifact(prompt, format, onEvent, signal),
      );
      return { output: null, streaming: true };
    },
  },

  "artifact-clear": {
    description: "Clear the artifact panel",
    handler: async () => {
      const { clearArtifact } = await import("./artifacts");
      await clearArtifact();
      return { output: "Artifact cleared." };
    },
  },

  tts: {
    description: "Toggle or set TTS mode",
    usage: "[off|auto|manual]",
    handler: async (args) => {
      const { getMode, setMode, getState } = await import("./tts");
      const target = args.trim().toLowerCase();

      if (!target) {
        // Toggle: off → auto → manual → off
        const current = getMode();
        const next = current === "off" ? "auto" : current === "auto" ? "manual" : "off";
        setMode(next);
        return { output: `TTS mode: **${next}**` };
      }

      const valid = ["off", "auto", "manual"] as const;
      if (!valid.includes(target as typeof valid[number])) {
        return { output: `Unknown TTS mode \`${target}\`. Valid: ${valid.join(", ")}` };
      }

      setMode(target as typeof valid[number]);
      const state = getState();
      return { output: `TTS mode: **${target}** (provider: ${state.provider})` };
    },
  },

  "tts-play": {
    description: "Read a message by index",
    usage: "<index>",
    handler: async (args, ctx) => {
      const { play, stop } = await import("./tts");
      const idx = parseInt(args.trim(), 10);

      if (isNaN(idx) || idx < 1 || idx > ctx.messages.length) {
        return { output: `Invalid index. Use 1-${ctx.messages.length}.` };
      }

      const msg = ctx.messages[idx - 1];
      stop();
      play(msg.content).catch((err) => console.warn("TTS playback failed:", err));
      return { output: null };
    },
  },

  "tts-stop": {
    description: "Stop TTS playback",
    handler: async () => {
      const { stop } = await import("./tts");
      stop();
      return { output: null };
    },
  },

  "tts-voice": {
    description: "Set or list browser TTS voices",
    usage: "[voice name]",
    handler: async (args) => {
      const { getBrowserVoices, setVoice, getState } = await import("./tts");
      const target = args.trim();

      if (!target) {
        const voices = getBrowserVoices();
        if (voices.length === 0) {
          return { output: "No browser voices available (voices may load after a moment)." };
        }
        const current = getState().voice;
        const lines = voices.map((v) => {
          const marker = v.name === current ? " **(active)**" : "";
          return `\`${v.name}\` — ${v.lang}${marker}`;
        });
        return { output: lines.join("\n") };
      }

      setVoice(target);
      return { output: `TTS voice set to: **${target}**` };
    },
  },

  "tts-provider": {
    description: "Switch TTS provider",
    usage: "[browser|server]",
    handler: async (args) => {
      const { setProvider, getState } = await import("./tts");
      const target = args.trim().toLowerCase();

      if (!target) {
        return { output: `Current TTS provider: **${getState().provider}**` };
      }

      if (target !== "browser" && target !== "server") {
        return { output: "Valid providers: `browser`, `server`" };
      }

      setProvider(target);
      return { output: `TTS provider set to: **${target}**` };
    },
  },

  imagine: {
    description: "Generate an image from a prompt (TBD)",
    usage: "<description>",
    handler: async (args) => {
      const prompt = args.trim();
      if (!prompt) {
        return { output: "Usage: `/imagine <description>`" };
      }

      const { requestImage } = await import("./api");
      try {
        const result = await requestImage(prompt);
        if (result.status === "ok" && result.image_url) {
          return { output: `![Generated image](${result.image_url})` };
        }
        return { output: result.error || "Image generation failed." };
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Request failed";
        // Parse 501 "not configured" responses
        if (msg.includes("501")) {
          return { output: "Image generation not yet configured. See `src/services/imagegen.py` to connect a backend." };
        }
        return { output: `Error: ${msg}` };
      }
    },
  },

  forge: {
    description: "Manage StoryForge projects",
    usage: "new <name> | start <name> | status <name> | pause <name> | approve <name> | list",
    handler: async (args, ctx) => {
      const parts = args.trim().split(/\s+/);
      const sub = parts[0]?.toLowerCase();
      const name = parts.slice(1).join("-");

      if (!sub || sub === "list") {
        try {
          const res = await fetch("/api/forge/projects");
          const data = await res.json();
          if (!data.projects?.length) {
            return { output: "No forge projects yet. Use `/forge new <name>` to create one." };
          }
          const lines = data.projects.map(
            (p: { name: string; stage: string; chapter_count: number; paused: boolean }) =>
              `- **${p.name}** — stage: ${p.stage}, chapters: ${p.chapter_count}${p.paused ? " (paused)" : ""}`,
          );
          return { output: lines.join("\n") };
        } catch {
          return { output: "Error listing forge projects." };
        }
      }

      if (sub === "new") {
        if (!name) return { output: "Usage: `/forge new <project-name>`" };
        try {
          const res = await fetch("/api/forge/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }),
          });
          const data = await res.json();
          if (data.status === "ok") {
            await ctx.setMode("forge" as Mode);
            return { output: `Forge project **${name}** created. You're now in planning mode — describe your story idea.` };
          }
          return { output: data.error || "Failed to create project." };
        } catch {
          return { output: "Error creating forge project." };
        }
      }

      if (sub === "start") {
        if (!name) return { output: "Usage: `/forge start <project-name>`" };
        const { sendForgeStream } = await import("./forge");
        await ctx.streamRequest((onEvent, signal) => sendForgeStream(name, onEvent, signal));
        return { output: null, streaming: true };
      }

      if (sub === "status") {
        if (!name) return { output: "Usage: `/forge status <project-name>`" };
        try {
          const res = await fetch(`/api/forge/${encodeURIComponent(name)}/status`);
          const data = await res.json();
          if (data.error) return { output: `Error: ${data.error}` };
          const m = data.manifest;
          const done = Object.values(m.chapters as Record<string, { status: string }>).filter(
            (c) => c.status === "done",
          ).length;
          const flagged = Object.values(m.chapters as Record<string, { status: string }>).filter(
            (c) => c.status === "flagged",
          ).length;
          return {
            output:
              `**${m.project_name}** — stage: ${m.stage}${m.paused ? " (paused)" : ""}\n` +
              `Chapters: ${done} done, ${flagged} flagged, ${m.chapter_count} total\n` +
              `Tokens: ${(m.stats.total_input_tokens + m.stats.total_output_tokens).toLocaleString()}`,
          };
        } catch {
          return { output: "Error fetching forge status." };
        }
      }

      if (sub === "pause") {
        if (!name) return { output: "Usage: `/forge pause <project-name>`" };
        try {
          const res = await fetch(`/api/forge/${encodeURIComponent(name)}/pause`, { method: "POST" });
          const data = await res.json();
          return { output: data.status === "ok" ? "Pipeline paused." : data.error || "Failed." };
        } catch {
          return { output: "Error pausing pipeline." };
        }
      }

      if (sub === "approve") {
        if (!name) return { output: "Usage: `/forge approve <project-name>`" };
        try {
          const res = await fetch(`/api/forge/${encodeURIComponent(name)}/approve`, { method: "POST" });
          const data = await res.json();
          return { output: data.status === "ok" ? "Chapter 1 approved. Run `/forge start " + name + "` to continue." : data.error || "Failed." };
        } catch {
          return { output: "Error approving chapter." };
        }
      }

      return { output: "Unknown subcommand. Usage: `/forge new|start|status|pause|approve|list`" };
    },
  },
};

/**
 * Check if input is a console command (starts with /).
 * Returns null if it's not a command.
 */
export function parseCommand(input: string): { name: string; args: string } | null {
  if (!input.startsWith("/")) return null;
  const match = input.match(/^\/(\S+)\s*(.*)/s);
  if (!match) return null;
  return { name: match[1].toLowerCase(), args: match[2] };
}

/**
 * Execute a parsed command. Returns null if the command doesn't exist.
 */
export async function executeCommand(
  name: string,
  args: string,
  ctx: CommandContext,
): Promise<CommandResult | null> {
  const cmd = commands[name];
  if (!cmd) return null;
  return cmd.handler(args, ctx);
}

/**
 * Get all registered command names (for autocomplete / hints).
 */
export function getCommandNames(): string[] {
  return Object.keys(commands).sort();
}
