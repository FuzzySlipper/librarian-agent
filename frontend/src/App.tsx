import { useCallback, useEffect, useRef, useState } from "react";
import { getMode, getStatus, newSession, sendChat } from "./api";
import type { Message, Mode, Status } from "./types";
import HeaderBar from "./components/HeaderBar";
import MessageBubble from "./components/MessageBubble";
import InputBar from "./components/InputBar";
import ProfilePicker from "./components/ProfilePicker";
import ModeSwitcher from "./components/ModeSwitcher";
import ContextOverlay from "./components/ContextOverlay";
import WriterControls from "./components/WriterControls";
import RoleplayControls from "./components/RoleplayControls";
import LoreBrowser from "./components/LoreBrowser";

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [mode, setMode] = useState<Mode>("general");
  const [hasPending, setHasPending] = useState(false);
  const [sending, setSending] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [modeOpen, setModeOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [loreOpen, setLoreOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

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
  }, [refreshStatus]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function doSend(text: string) {
    setSending(true);
    try {
      const data = await sendChat(text);
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.content,
        responseType: data.response_type,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      refreshStatus();
    } catch (err) {
      const errorMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `Error: ${err instanceof Error ? err.message : "Connection failed"}`,
        responseType: "error",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setSending(false);
    }
  }

  async function handleSend(text: string) {
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    await doSend(text);
  }

  function handleEditMessage(id: string, newContent: string) {
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, content: newContent } : m)),
    );
  }

  // Writer mode: send "accept" or "regenerate" as chat commands
  async function handleAccept() {
    await doSend("accept");
  }

  async function handleRegenerate() {
    await doSend("regenerate");
  }

  // Roleplay mode
  async function handleDeleteLast() {
    await doSend("delete");
    // Remove the last assistant message from local state too
    setMessages((prev) => {
      const lastAssistantIdx = [...prev].reverse().findIndex((m) => m.role === "assistant");
      if (lastAssistantIdx === -1) return prev;
      const idx = prev.length - 1 - lastAssistantIdx;
      return [...prev.slice(0, idx), ...prev.slice(idx + 1)];
    });
  }

  const hasAssistantMessages = messages.some((m) => m.role === "assistant");

  return (
    <div className="h-dvh flex flex-col bg-bg">
      <HeaderBar
        status={status}
        onOpenProfile={() => setProfileOpen(true)}
        onOpenMode={() => setModeOpen(true)}
        onOpenContext={() => setContextOpen(true)}
        onOpenLore={() => setLoreOpen(true)}
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
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            onEdit={msg.role === "user" ? handleEditMessage : undefined}
          />
        ))}
        {sending && (
          <div className="text-text-muted italic text-sm px-4 py-2">
            thinking...
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
    </div>
  );
}

export default App;
