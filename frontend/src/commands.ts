import type { Mode, Status } from "./types";
import type { StreamEvent } from "./api";

export interface CommandContext {
  /** Current app status */
  status: Status | null;
  /** Current mode */
  mode: Mode;
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
