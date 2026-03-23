import { useCallback, useEffect, useRef, useState } from "react";
import { getMode, getStatus, newSession, sendChatStream, setMode as apiSetMode, conversationDelete, conversationFork, conversationUpdate } from "./api";
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
import SessionBrowser from "./components/SessionBrowser";
import CharacterCards from "./components/CharacterCards";
import TextThemePicker from "./components/TextThemePicker";
import * as textTheme from "./textTheme";
import type { TextTheme } from "./textTheme";

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
  const [backgroundImage, setBackgroundImage] = useState<string | null>(layoutManager.getBackground());
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
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [charactersOpen, setCharactersOpen] = useState(false);
  const [textThemeOpen, setTextThemeOpen] = useState(false);
  const [portraits, setPortraits] = useState<{ filename: string; url: string }[]>([]);
  const [currentTextTheme, setCurrentTextTheme] = useState<TextTheme>(textTheme.getTheme());
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // When true, the next response will be added as a variant to the last assistant message
  const addAsVariantRef = useRef(false);
  const [elapsed, setElapsed] = useState(0);
  const elapsedRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
    tts.init();
    textTheme.init();
    textTheme.setOnChange(setCurrentTextTheme);
    layoutManager.setOnLayoutChange(setLayout);
    layoutManager.setOnBackgroundChange(setBackgroundImage);
    artifactManager.setOnArtifactChange(setArtifact);
    artifactManager.init();

    // Fetch status first, then init layout with the configured default
    getStatus()
      .then((s) => {
        setStatus(s);
        setMode(s.mode);
        layoutManager.init(s.layout);
      })
      .catch(() => {
        setStatus(null);
        layoutManager.init();
      });
    getMode()
      .then((m) => setHasPending(m.pending_content))
      .catch(() => {});
    fetch("/api/portraits")
      .then((r) => r.json())
      .then((d) => setPortraits(d.portraits ?? []))
      .catch(() => {});
  }, []);

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
    setElapsed(0);
    if (elapsedRef.current) clearInterval(elapsedRef.current);
    elapsedRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
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
            // Apply user portrait to the preceding user message
            const userPortrait = event.data.user_portrait as string | null | undefined;
            if (userPortrait) {
              setMessages((prev) =>
                prev.map((m, i) => {
                  // Find the last user message
                  const isLastUser = m.role === "user" && !prev.slice(i + 1).some((n) => n.role === "user");
                  return isLastUser ? { ...m, userPortrait } : m;
                }),
              );
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
      if (elapsedRef.current) { clearInterval(elapsedRef.current); elapsedRef.current = null; }
    }
  }

  async function handleSend(text: string) {
    const parsed = parseCommand(text);

    if (parsed) {
      // Show the command in chat as a user message
      const cmdMsg: Message = {
        id: uuid(),
        role: "user",
        content: text,
        responseType: "command",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, cmdMsg]);

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
          // Reuse the same streaming UI as doSend, with text_delta support
          setSending(true);
          setStreamStatus("Connecting...");
          setElapsed(0);
          if (elapsedRef.current) clearInterval(elapsedRef.current);
          elapsedRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
          const abort = new AbortController();
          abortRef.current = abort;

          const reqStreamMsgId = uuid();
          let reqStreamStarted = false;
          let reqAccText = "";

          try {
            await fetcher(
              (event) => {
                if (event.type === "status") {
                  setStreamStatus(event.data.message as string);
                } else if (event.type === "tool") {
                  setStreamStatus(`Using ${event.data.name}...`);
                } else if (event.type === "text_delta") {
                  reqAccText += event.data.text as string;
                  if (!reqStreamStarted) {
                    reqStreamStarted = true;
                    setStreamStatus(null);
                    setMessages((prev) => [
                      ...prev,
                      { id: reqStreamMsgId, role: "assistant", content: reqAccText, responseType: "streaming", timestamp: Date.now() },
                    ]);
                  } else {
                    const text = reqAccText;
                    setMessages((prev) =>
                      prev.map((m) => m.id === reqStreamMsgId ? { ...m, content: text } : m),
                    );
                  }
                } else if (event.type === "done") {
                  if (reqStreamStarted) {
                    setMessages((prev) => prev.filter((m) => m.id !== reqStreamMsgId));
                  }
                  addResponseMessage(
                    event.data.content as string,
                    event.data.response_type as string,
                    event.data.portrait as string | null | undefined,
                  );
                  setStreamStatus(null);
                  refreshStatus();
                } else if (event.type === "error") {
                  if (reqStreamStarted) {
                    setMessages((prev) => prev.filter((m) => m.id !== reqStreamMsgId));
                  }
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
            if (elapsedRef.current) { clearInterval(elapsedRef.current); elapsedRef.current = null; }
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

    // Normal LLM message — sync variant selections first
    await syncVariantSelections();
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
      // Retry as a swipeable variant — keep the message, add new response as variant
      addAsVariantRef.current = true;
      await doSend("regenerate");
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

  async function handleDeleteMessage(id: string) {
    // Find the message's backend index (only user+assistant messages count)
    const nonSystemMessages = messages.filter((m) => m.role !== "system");
    const backendIdx = nonSystemMessages.findIndex((m) => m.id === id);
    if (backendIdx === -1) return;

    try {
      await conversationDelete(backendIdx);
      // Remove from frontend: delete user+assistant pair
      const msg = messages.find((m) => m.id === id);
      if (!msg) return;
      setMessages((prev) => {
        const msgIdx = prev.findIndex((m) => m.id === id);
        if (msgIdx === -1) return prev;
        if (msg.role === "user") {
          // Delete user and following assistant (if exists)
          const next = prev[msgIdx + 1];
          const end = next && next.role === "assistant" ? msgIdx + 2 : msgIdx + 1;
          return [...prev.slice(0, msgIdx), ...prev.slice(end)];
        } else {
          // Delete assistant and preceding user (if exists)
          const prev2 = prev[msgIdx - 1];
          const start = prev2 && prev2.role === "user" ? msgIdx - 1 : msgIdx;
          return [...prev.slice(0, start), ...prev.slice(msgIdx + 1)];
        }
      });
      refreshStatus();
    } catch (err) {
      addSystemMessage(`Failed to delete message: ${err instanceof Error ? err.message : "unknown error"}`);
    }
  }

  async function handleForkMessage(id: string) {
    const nonSystemMessages = messages.filter((m) => m.role !== "system");
    const backendIdx = nonSystemMessages.findIndex((m) => m.id === id);
    if (backendIdx === -1) return;

    try {
      const result = await conversationFork(backendIdx);
      addSystemMessage(`Forked conversation saved as session (${result.turns} turns). Open Sessions to load it.`);
    } catch {
      addSystemMessage("Failed to fork conversation.");
    }
  }

  /**
   * When the user sends a new message, sync any active variant selections
   * to the backend so it uses the right content in history.
   */
  async function syncVariantSelections() {
    const nonSystem = messages.filter((m) => m.role !== "system");
    for (let i = 0; i < nonSystem.length; i++) {
      const m = nonSystem[i];
      if (m.variants && m.variants.length > 1 && m.activeVariant !== undefined) {
        const selected = m.variants[m.activeVariant];
        // Only sync if the selected variant differs from what the backend has
        // (backend always has the last response, but we may have swiped)
        await conversationUpdate(i, selected.content).catch(() => {});
      }
    }
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
        onOpenSessions={() => setSessionsOpen(true)}
        onOpenCharacters={() => setCharactersOpen(true)}
        onOpenTextTheme={() => setTextThemeOpen(true)}
        textThemeName={currentTextTheme.name}
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
        {messages.map((msg, i) => {
          // Compute index excluding system messages (matches backend history indices)
          const msgIndex = msg.role === "system" ? 0 : messages.slice(0, i + 1).filter((m) => m.role !== "system").length;
          return (
          <MessageBubble
            key={msg.id}
            message={msg}
            index={msgIndex}
            mode={mode}
            onEdit={msg.role !== "system" ? handleEditMessage : undefined}
            onRetry={msg.role !== "system" ? handleRetry : undefined}
            onSwipe={msg.role === "assistant" ? handleSwipe : undefined}
            onDelete={msg.role !== "system" ? handleDeleteMessage : undefined}
            onFork={msg.role !== "system" ? handleForkMessage : undefined}
          />
          );
        })}
        {sending && (
          <div className="flex items-center gap-2 text-text-muted italic text-sm px-4 py-2">
            <span className="inline-block w-2 h-2 rounded-full bg-accent animate-pulse" />
            <span>{streamStatus || "Working..."}</span>
            <span className="text-text-muted/40 text-xs font-mono tabular-nums">{elapsed}s</span>
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
      <CharacterCards
        open={charactersOpen}
        onClose={() => setCharactersOpen(false)}
        onChanged={refreshStatus}
        portraits={portraits}
      />
      <TextThemePicker
        open={textThemeOpen}
        onClose={() => setTextThemeOpen(false)}
        onChanged={() => setCurrentTextTheme(textTheme.getTheme())}
      />
      <SessionBrowser
        open={sessionsOpen}
        onClose={() => setSessionsOpen(false)}
        onLoad={(msgs, _loadedMode) => {
          // Convert backend messages to frontend Message objects
          const restored: Message[] = msgs.map((m, i) => ({
            id: uuid(),
            role: m.role as "user" | "assistant",
            content: m.content,
            timestamp: Date.now() - (msgs.length - i) * 1000,
          }));
          setMessages(restored);
          setHasPending(false);
          refreshStatus();
        }}
      />
    </div>
  );

  return (
    <LayoutShell layout={layout} chatContent={chatContent} artifact={artifact} backgroundImage={backgroundImage} />
  );
}

export default App;
