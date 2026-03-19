/**
 * TTS (Text-to-Speech) manager.
 *
 * Supports two provider paths:
 *   - "browser": Uses the Web Speech API (zero config, client-side only)
 *   - Server-backed: Calls /api/tts which returns audio data
 *
 * Modes:
 *   - "off": No TTS
 *   - "auto": Automatically reads every assistant message
 *   - "manual": Only plays when explicitly triggered via /tts-play
 */

export type TTSMode = "off" | "auto" | "manual";

interface TTSState {
  mode: TTSMode;
  provider: "browser" | "server";
  playing: boolean;
  voice: string; // browser voice name
}

const state: TTSState = {
  mode: "off",
  provider: "browser",
  playing: false,
  voice: "",
};

let currentUtterance: SpeechSynthesisUtterance | null = null;
let currentAudio: HTMLAudioElement | null = null;

// Callbacks for UI updates
let onStateChange: ((state: TTSState) => void) | null = null;

export function setOnStateChange(cb: (state: TTSState) => void) {
  onStateChange = cb;
}

function notify() {
  onStateChange?.(getState());
}

export function getState(): TTSState {
  return { ...state };
}

export function getMode(): TTSMode {
  return state.mode;
}

export function setMode(mode: TTSMode) {
  state.mode = mode;
  notify();
}

export function setProvider(provider: "browser" | "server") {
  state.provider = provider;
  notify();
}

export function setVoice(voice: string) {
  state.voice = voice;
  notify();
}

/**
 * Get available browser voices.
 */
export function getBrowserVoices(): SpeechSynthesisVoice[] {
  if (!("speechSynthesis" in window)) return [];
  return speechSynthesis.getVoices();
}

/**
 * Stop any currently playing TTS.
 */
export function stop() {
  if (currentUtterance) {
    speechSynthesis.cancel();
    currentUtterance = null;
  }
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.src = "";
    currentAudio = null;
  }
  state.playing = false;
  notify();
}

/**
 * Strip markdown formatting for cleaner TTS output.
 */
function stripMarkdown(text: string): string {
  return text
    .replace(/#{1,6}\s+/g, "")      // headers
    .replace(/\*\*(.+?)\*\*/g, "$1") // bold
    .replace(/\*(.+?)\*/g, "$1")     // italic
    .replace(/_(.+?)_/g, "$1")       // italic alt
    .replace(/`(.+?)`/g, "$1")       // inline code
    .replace(/```[\s\S]*?```/g, "")  // code blocks
    .replace(/\[(.+?)\]\(.+?\)/g, "$1") // links
    .replace(/^[-*+]\s+/gm, "")     // list markers
    .replace(/^\d+\.\s+/gm, "")     // numbered lists
    .replace(/^>\s+/gm, "")         // blockquotes
    .replace(/---+/g, "")           // hr
    .trim();
}

/**
 * Play text via the browser's Web Speech API.
 */
function playBrowser(text: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!("speechSynthesis" in window)) {
      reject(new Error("Browser speech synthesis not available"));
      return;
    }

    stop();

    const cleaned = stripMarkdown(text);
    const utterance = new SpeechSynthesisUtterance(cleaned);

    if (state.voice) {
      const voices = speechSynthesis.getVoices();
      const match = voices.find(
        (v) => v.name === state.voice || v.name.toLowerCase().includes(state.voice.toLowerCase()),
      );
      if (match) utterance.voice = match;
    }

    currentUtterance = utterance;
    state.playing = true;
    notify();

    utterance.onend = () => {
      state.playing = false;
      currentUtterance = null;
      notify();
      resolve();
    };

    utterance.onerror = (e) => {
      state.playing = false;
      currentUtterance = null;
      notify();
      reject(new Error(e.error));
    };

    speechSynthesis.speak(utterance);
  });
}

/**
 * Play text via the server TTS endpoint.
 */
async function playServer(text: string): Promise<void> {
  stop();

  const cleaned = stripMarkdown(text);
  const resp = await fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: cleaned }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: "TTS request failed" }));
    throw new Error(err.error || `TTS error: ${resp.status}`);
  }

  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  currentAudio = audio;
  state.playing = true;
  notify();

  return new Promise((resolve, reject) => {
    audio.onended = () => {
      URL.revokeObjectURL(url);
      state.playing = false;
      currentAudio = null;
      notify();
      resolve();
    };

    audio.onerror = () => {
      URL.revokeObjectURL(url);
      state.playing = false;
      currentAudio = null;
      notify();
      reject(new Error("Audio playback failed"));
    };

    audio.play().catch((e) => {
      state.playing = false;
      currentAudio = null;
      notify();
      reject(e);
    });
  });
}

/**
 * Play text using the currently configured provider.
 */
export async function play(text: string): Promise<void> {
  if (state.provider === "browser") {
    return playBrowser(text);
  }
  return playServer(text);
}

/**
 * Called when a new assistant message arrives (for auto mode).
 */
export function onAssistantMessage(text: string) {
  if (state.mode === "auto") {
    play(text).catch((err) => {
      console.warn("TTS auto-play failed:", err);
    });
  }
}

/**
 * Initialize TTS — check what providers are available.
 */
export async function init(): Promise<void> {
  try {
    const resp = await fetch("/api/tts/providers");
    if (resp.ok) {
      const data = await resp.json();
      // Default to server if available, otherwise browser
      if (data.has_server) {
        state.provider = "server";
      } else if (data.has_browser || "speechSynthesis" in window) {
        state.provider = "browser";
      }
    }
  } catch {
    // Server not available, default to browser
    if ("speechSynthesis" in window) {
      state.provider = "browser";
    }
  }
}
