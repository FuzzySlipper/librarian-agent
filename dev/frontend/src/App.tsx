import { useCallback, useEffect, useRef, useState } from "react";
import { getMode, getStatus, newSession, sendChatStream, setMode as apiSetMode } from "./api";
import type { Message, MessageVariant, Mode, Status } from "./types";
import { parseCommand, executeCommand } from "./commands";
import type { CommandContext } from "./commands";
import * as tts from "./tts";
import * as layoutManager from "./layout";
import type { LayoutConfig } from "./layout";
import * as artifactManager from "./artifacts";
import type { Artifact } from "./artifacts";
import LayoutShell from "./components/LayoutShell";
import HeaderBar from "./components/HeaderBar";
import MessageBubble from "./components/MessageBubble";
import InputBar from "./components/InputBar";
import ProfilePicker from "./components/ProfilePicker";
import ModeSwitcher from "./components/ModeSwitcher";
import ContextOverlay from "./components/ContextOverlay";
import WriterControls from "./components/WriterControls";
import RoleplayControls from "./components/RoleplayControls";
import LoreBrowser from "./components/LoreBrowser";
import PromptBrowser from "./components/PromptBrowser";
import LayoutPicker from "./components/LayoutPicker";
import ProviderManager from "./components/ProviderManager";

/** uuid() requires a secure context (HTTPS); fall back for plain HTTP. */
const uuid = (): string =>
  typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
      });

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [mode, setMode] = useState<Mode>("general");
  const [layout, setLayout] = useState<LayoutConfig>(layoutManager.getLayout());
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [hasPending, setHasPending] = useState(false);
  const [sending, setSending] = useState(false);
  const [streamStatus, setStreamStatus] = useState<string | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [modeOpen, setModeOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [loreOpen, setLoreOpen] = useState(false);
  const [promptsOpen, setPromptsOpen] = useState(false);
  const [layoutOpen, setLayoutOpen] = useState(false);
  const [providerOpen, setProviderOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // When true, the next response will be added as a variant to the last assistant message
  const addAsVariantRef = useRef(false);

  const refreshStatus = useCallback(() => {
    getStatus()
      .then((s) => {
        setStatus(s);
        setMode(s.mode);
      })
      .catch(() => setStatus(null));
    getMode()
      .then((m) => setHasPending(m.pending_content))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshStatus();
    tts.init();
    layoutManager.setOnLayoutChange(setLayout);
    layoutManager.init();
    artifactManager.setOnArtifactChange(setArtifact);
    artifactManager.init();
  }, [refreshStatus]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamStatus]);

  function addResponseMessage(content: string, responseType: string, portrait?: string | null, reasoning?: string | null) {
    if (addAsVariantRef.current) {
      // Add as a variant to the last assistant message
      addAsVariantRef.current = false;
      setMessages((prev) => {
        const lastIdx = [...prev].reverse().findIndex((m) => m.role === "assistant");
        if (lastIdx === -1) {
          return [...prev, makeAssistantMsg(content, responseType, portrait, reasoning)];
        }
        const idx = prev.length - 1 - lastIdx;
        const msg = prev[idx];
        const variants: MessageVariant[] = msg.variants ?? [
          { content: msg.content, responseType: msg.responseType, timestamp: msg.timestamp, portrait: msg.portrait, reasoning: msg.reasoning },
        ];
        const newVariant: MessageVariant = { content, responseType, timestamp: Date.now(), portrait, reasoning };
        const newVariants = [...variants, newVariant];
        const newIdx = newVariants.length - 1;

        return [
          ...prev.slice(0, idx),
          {
            ...msg,
            content,
            responseType,
            portrait,
            reasoning,
            variants: newVariants,
            activeVariant: newIdx,
          },
          ...prev.slice(idx + 1),
        ];
      });
    } else {
      setMessages((prev) => [...prev, makeAssistantMsg(content, responseType, portrait, reasoning)]);
    }
    // Auto TTS for new assistant messages
    tts.onAssistantMessage(content);
  }

  function makeAssistantMsg(content: string, responseType: string, portrait?: string | null, reasoning?: string | null): Message {
    return {
      id: uuid(),
      role: "assistant",
      content,
      responseType,
      portrait,
      reasoning,
      timestamp: Date.now(),
    };
  }

  async function doSend(text: string) {
    setSending(true);
    setStreamStatus("Connecting...");
    const abort = new AbortController();
    abortRef.current = abort;

    // Track the live-streaming message
    const streamMsgId = uuid();
    let streamingStarted = false;
    let accText = "";
    let accReasoning = "";

    try {
      await sendChatStream(
        text,
        (event) => {
          if (event.type === "status") {
            setStreamStatus(event.data.message as string);
          } else if (event.type === "tool") {
            setStreamStatus(`Using ${event.data.name}...`);
            // If we were streaming text before a tool call, clear the streaming msg
            if (streamingStarted) {
              setMessages((prev) => prev.filter((m) => m.id !== streamMsgId));
              streamingStarted = false;
              accText = "";
              accReasoning = "";
            }
          } else if (event.type === "text_delta") {
            accText += event.data.text as string;
            if (!streamingStarted) {
              streamingStarted = true;
              setStreamStatus(null);
              setMessages((prev) => [
                ...prev,
                {
                  id: streamMsgId,
                  role: "assistant",
                  content: accText,
                  responseType: "streaming",
                  reasoning: accReasoning || null,
                  timestamp: Date.now(),
                },
              ]);
            } else {
              const currentText = accText;
              const currentReasoning = accReasoning;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === streamMsgId
                    ? { ...m, content: currentText, reasoning: currentReasoning || null }
                    : m,
                ),
              );
            }
          } else if (event.type === "reasoning_delta") {
            accReasoning += event.data.text as string;
            if (streamingStarted) {
              const currentText = accText;
              const currentReasoning = accReasoning;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === streamMsgId
                    ? { ...m, content: currentText, reasoning: currentReasoning || null }
                    : m,
                ),
              );
            }
          } else if (event.type === "done") {
            // Remove streaming message and add final one
            if (streamingStarted) {
              setMessages((prev) => prev.filter((m) => m.id !== streamMsgId));
            }
            const reasoning = (event.data.reasoning as string) || null;
            const msg = makeAssistantMsg(
              event.data.content as string,
              event.data.response_type as string,
              event.data.portrait as string | null | undefined,
            );
            if (reasoning) {
              msg.reasoning = reasoning;
            }
            addResponseMessage(
              msg.content,
              msg.responseType || "discussion",
              msg.portrait,
              msg.reasoning,
            );
            setStreamStatus(null);
            refreshStatus();
          } else if (event.type === "error") {
            if (streamingStarted) {
              setMessages((prev) => prev.filter((m) => m.id !== streamMsgId));
            }
            addResponseMessage(`Error: ${event.data.message}`, "error");
            setStreamStatus(null);
          }
        },
        abort.signal,
      );
    } catch (err) {
      if (streamingStarted) {
        setMessages((prev) => prev.filter((m) => m.id !== streamMsgId));
      }
      if ((err as Error).name !== "AbortError") {
        addResponseMessage(
          `Error: ${err instanceof Error ? err.message : "Connection failed"}`,
          "error",
        );
      }
      setStreamStatus(null);
    } finally {
      setSending(false);
      abortRef.current = null;
    }
  }

  async function handleSend(text: string) {
    const parsed = parseCommand(text);

    if (parsed) {
      // Build command context
      const ctx: CommandContext = {
        status,
        mode,
        messages,
        openProfile: () => setProfileOpen(true),
        openMode: () => setModeOpen(true),
        openLore: () => setLoreOpen(true),
        openContext: () => setContextOpen(true),
        newSession: async () => {
          await newSession();
          setMessages([]);
          setHasPending(false);
          refreshStatus();
        },
        clearMessages: () => setMessages([]),
        setMode: async (m: Mode) => {
          await apiSetMode(m);
          refreshStatus();
        },
        refreshStatus,
        streamRequest: async (fetcher) => {
          // Reuse the same streaming UI as doSend
          setSending(true);
          setStreamStatus("Connecting...");
          const abort = new AbortController();
          abortRef.current = abort;

          try {
            await fetcher(
              (event) => {
                if (event.type === "status") {
                  setStreamStatus(event.data.message as string);
                } else if (event.type === "tool") {
                  setStreamStatus(`Using ${event.data.name}...`);
                } else if (event.type === "done") {
                  addResponseMessage(
                    event.data.content as string,
                    event.data.response_type as string,
                    event.data.portrait as string | null | undefined,
                  );
                  setStreamStatus(null);
                  refreshStatus();
                } else if (event.type === "error") {
                  addResponseMessage(`Error: ${event.data.message}`, "error");
                  setStreamStatus(null);
                }
              },
              abort.signal,
            );
          } catch (err) {
            if ((err as Error).name !== "AbortError") {
              addResponseMessage(
                `Error: ${err instanceof Error ? err.message : "Connection failed"}`,
                "error",
              );
            }
            setStreamStatus(null);
          } finally {
            setSending(false);
            abortRef.current = null;
          }
        },
      };

      const result = await executeCommand(parsed.name, parsed.args, ctx);
      if (result === null) {
        // Unknown command — show error
        addSystemMessage(`Unknown command \`/${parsed.name}\`. Type \`/help\` for available commands.`);
      } else if (result.output) {
        addSystemMessage(result.output);
      }
      return;
    }

    // Normal LLM message
    const userMsg: Message = {
      id: uuid(),
      role: "user",
      content: text,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    addAsVariantRef.current = false;
    await doSend(text);
  }

  function addSystemMessage(content: string) {
    const msg: Message = {
      id: uuid(),
      role: "system",
      content,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, msg]);
  }

  function handleStop() {
    abortRef.current?.abort();
  }

  function handleEditMessage(id: string, newContent: string) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, content: newContent } : m)),
    );
  }

  async function handleRetry(id: string) {
    // Find the message being retried
    const idx = messages.findIndex((m) => m.id === id);
    if (idx === -1) return;

    const msg = messages[idx];

    if (msg.role === "user") {
      // Retrying a user message: trim everything after it and re-send
      setMessages((prev) => prev.slice(0, idx + 1));
      addAsVariantRef.current = false;
      await doSend(msg.content);
    } else if (msg.role === "assistant") {
      // Retrying from an assistant message: find the user message before it,
      // trim from the assistant message onward, and re-send
      let userIdx = -1;
      for (let i = idx - 1; i >= 0; i--) {
        if (messages[i].role === "user") { userIdx = i; break; }
      }
      if (userIdx === -1) return;
      const userContent = messages[userIdx].content;
      setMessages((prev) => prev.slice(0, userIdx + 1));
      addAsVariantRef.current = false;
      await doSend(userContent);
    }
  }

  function handleSwipe(id: string, direction: "prev" | "next") {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== id || !m.variants) return m;
        const current = m.activeVariant ?? 0;
        const next = direction === "prev" ? current - 1 : current + 1;
        if (next < 0 || next >= m.variants.length) return m;
        const variant = m.variants[next];
        return {
          ...m,
          content: variant.content,
          responseType: variant.responseType,
          portrait: variant.portrait,
          activeVariant: next,
        };
      }),
    );
  }

  async function handleAccept() {
    await doSend("accept");
  }

  async function handleRegenerate() {
    addAsVariantRef.current = true;
    await doSend("regenerate");
  }

  async function handleDeleteLast() {
    await doSend("delete");
    setMessages((prev) => {
      const lastAssistantIdx = [...prev].reverse().findIndex((m) => m.role === "assistant");
      if (lastAssistantIdx === -1) return prev;
      const idx = prev.length - 1 - lastAssistantIdx;
      return [...prev.slice(0, idx), ...prev.slice(idx + 1)];
    });
  }

  const hasAssistantMessages = messages.some((m) => m.role === "assistant");

  const chatContent = (
    <div className="h-dvh flex flex-col bg-bg">
      <HeaderBar
        status={status}
        layoutName={layout.name}
        onOpenProfile={() => setProfileOpen(true)}
        onOpenMode={() => setModeOpen(true)}
        onOpenContext={() => setContextOpen(true)}
        onOpenLore={() => setLoreOpen(true)}
        onOpenPrompts={() => setPromptsOpen(true)}
        onOpenLayout={() => setLayoutOpen(true)}
        onOpenProviders={() => setProviderOpen(true)}
        onNewSession={async () => {
          await newSession();
          setMessages([]);
          setHasPending(false);
          refreshStatus();
        }}
      />

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
        {messages.length === 0 && (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center text-text-muted">
              <p className="text-lg mb-2">Ready to go</p>
              <p className="text-sm">
                {status?.status === "ready"
                  ? `${status.mode} mode · ${status.lore_files} lore files loaded`
                  : "Connecting..."}
              </p>
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            index={i + 1}
            mode={mode}
            onEdit={msg.role !== "system" ? handleEditMessage : undefined}
            onRetry={msg.role !== "system" ? handleRetry : undefined}
            onSwipe={msg.role === "assistant" ? handleSwipe : undefined}
          />
        ))}
        {sending && streamStatus && (
          <div className="flex items-center gap-2 text-text-muted italic text-sm px-4 py-2">
            <span className="inline-block w-2 h-2 rounded-full bg-accent animate-pulse" />
            <span>{streamStatus}</span>
            <button
              onClick={handleStop}
              className="ml-auto text-xs bg-surface-alt hover:bg-border text-text-muted hover:text-text rounded px-2 py-1 transition-colors"
            >
              Stop
            </button>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {mode === "writer" && (
        <WriterControls
          hasPending={hasPending}
          onAccept={handleAccept}
          onRegenerate={handleRegenerate}
          disabled={sending}
        />
      )}

      {mode === "roleplay" && (
        <RoleplayControls
          hasMessages={hasAssistantMessages}
          onRegenerate={handleRegenerate}
          onDeleteLast={handleDeleteLast}
          disabled={sending}
        />
      )}

      <InputBar onSend={handleSend} disabled={sending} />

      <ProfilePicker
        open={profileOpen}
        onClose={() => setProfileOpen(false)}
        onSwitched={refreshStatus}
      />
      <ModeSwitcher
        open={modeOpen}
        onClose={() => setModeOpen(false)}
        onSwitched={refreshStatus}
      />
      <ContextOverlay
        open={contextOpen}
        onClose={() => setContextOpen(false)}
        status={status}
      />
      <LoreBrowser
        open={loreOpen}
        onClose={() => setLoreOpen(false)}
        onChanged={refreshStatus}
      />
      <PromptBrowser
        open={promptsOpen}
        onClose={() => setPromptsOpen(false)}
        onChanged={refreshStatus}
      />
      <LayoutPicker
        open={layoutOpen}
        onClose={() => setLayoutOpen(false)}
      />
      <ProviderManager
        open={providerOpen}
        onClose={() => setProviderOpen(false)}
        onChanged={refreshStatus}
      />
    </div>
  );

  return (
    <LayoutShell layout={layout} chatContent={chatContent} artifact={artifact} />
  );
}

export default App;
