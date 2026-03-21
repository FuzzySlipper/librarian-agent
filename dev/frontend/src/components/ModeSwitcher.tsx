import { useEffect, useState } from "react";
import Overlay from "./Overlay";
import { getMode, getProjects, setMode, listCharacterCards, type CharacterCardSummary } from "../api";
import type { Mode, ModeInfo } from "../types";

interface ModeSwitcherProps {
  open: boolean;
  onClose: () => void;
  onSwitched: () => void;
}

const MODE_LABELS: Record<Mode, string> = {
  general: "General",
  writer: "Writer",
  roleplay: "Roleplay",
  forge: "Forge",
  council: "Council",
};

const MODE_DESCRIPTIONS: Record<Mode, string> = {
  general: "Free-form routing — the orchestrator decides what you need.",
  writer: "Project-based writing with accept/reject/regenerate flow.",
  roleplay: "Chat-based roleplay with a character card.",
  forge: "Automated story generation pipeline with planning and chapter drafting.",
  council: "Every message is routed through the council for multiple perspectives before synthesis.",
};

export default function ModeSwitcher({ open, onClose, onSwitched }: ModeSwitcherProps) {
  const [current, setCurrent] = useState<ModeInfo | null>(null);
  const [selectedMode, setSelectedMode] = useState<Mode>("general");
  const [projects, setProjects] = useState<{ name: string; files: string[] }[]>([]);
  const [project, setProject] = useState("");
  const [saving, setSaving] = useState(false);

  // Roleplay character selection
  const [characters, setCharacters] = useState<CharacterCardSummary[]>([]);
  const [selectedCharacter, setSelectedCharacter] = useState("");

  useEffect(() => {
    if (!open) return;
    getMode().then((m) => {
      setCurrent(m);
      setSelectedMode(m.mode);
      setProject(m.project || "");
    });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (selectedMode === "roleplay") {
      // Fetch character cards for roleplay mode
      listCharacterCards().then((data) => {
        setCharacters(data.cards);
        setSelectedCharacter(data.active_ai || "");
      });
    } else if (selectedMode !== "general" && selectedMode !== "council") {
      // Fetch projects for writer/forge
      getProjects(selectedMode).then((p) => setProjects(p.projects));
    }
  }, [open, selectedMode]);

  async function handleApply() {
    setSaving(true);
    try {
      if (selectedMode === "roleplay") {
        await setMode(selectedMode, undefined, undefined, selectedCharacter || undefined);
      } else {
        await setMode(selectedMode, project || undefined);
      }
      onSwitched();
      onClose();
    } finally {
      setSaving(false);
    }
  }

  const needsProject = selectedMode === "writer" || selectedMode === "forge";
  const needsCharacter = selectedMode === "roleplay";
  const canApply =
    selectedMode === "general" ||
    selectedMode === "council" ||
    (needsProject && !!project) ||
    (needsCharacter && !!selectedCharacter);

  return (
    <Overlay open={open} onClose={onClose} title="Mode">
      {current ? (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            {(Object.keys(MODE_LABELS) as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => setSelectedMode(m)}
                className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  selectedMode === m
                    ? "bg-accent text-white"
                    : "bg-input-bg text-text-muted hover:text-text border border-border"
                }`}
              >
                {MODE_LABELS[m]}
              </button>
            ))}
          </div>

          <p className="text-sm text-text-muted">{MODE_DESCRIPTIONS[selectedMode]}</p>

          {/* Writer / Forge: project selector */}
          {needsProject && (
            <label className="flex flex-col gap-1">
              <span className="text-sm text-text-muted">Project</span>
              <div className="flex gap-2">
                <select
                  value={project}
                  onChange={(e) => setProject(e.target.value)}
                  className="flex-1 bg-input-bg text-text border border-border rounded-lg px-3 py-2"
                >
                  <option value="">Select or type new...</option>
                  {projects.map((p) => (
                    <option key={p.name} value={p.name}>{p.name}</option>
                  ))}
                </select>
                <input
                  type="text"
                  value={project}
                  onChange={(e) => setProject(e.target.value)}
                  placeholder="New project"
                  className="flex-1 bg-input-bg text-text border border-border rounded-lg px-3 py-2"
                />
              </div>
            </label>
          )}

          {/* Roleplay: character selector */}
          {needsCharacter && (
            <label className="flex flex-col gap-1">
              <span className="text-sm text-text-muted">Character (AI plays)</span>
              {characters.length === 0 ? (
                <p className="text-sm text-text-muted/70">
                  No character cards yet. Create one in the Characters menu first.
                </p>
              ) : (
                <div className="flex flex-col gap-1.5 mt-1">
                  {characters.map((c) => (
                    <button
                      key={c.filename}
                      onClick={() => setSelectedCharacter(c.filename)}
                      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${
                        selectedCharacter === c.filename
                          ? "bg-accent/20 ring-1 ring-accent/50"
                          : "hover:bg-input-bg bg-input-bg/30"
                      }`}
                    >
                      {c.portrait ? (
                        <img
                          src={`/portraits/${c.portrait}`}
                          alt=""
                          className="w-9 h-9 rounded-full object-cover ring-1 ring-border shrink-0"
                        />
                      ) : (
                        <div className="w-9 h-9 rounded-full bg-surface-alt ring-1 ring-border shrink-0 flex items-center justify-center text-text-muted text-xs">
                          ?
                        </div>
                      )}
                      <span className={`text-sm ${selectedCharacter === c.filename ? "text-accent" : "text-text"}`}>
                        {c.name}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </label>
          )}

          <button
            onClick={handleApply}
            disabled={saving || !canApply}
            className="mt-2 bg-accent hover:bg-accent-hover text-white font-semibold rounded-lg px-4 py-2.5 disabled:opacity-50 transition-colors"
          >
            {saving ? "Switching..." : "Apply"}
          </button>
        </div>
      ) : (
        <p className="text-text-muted">Loading...</p>
      )}
    </Overlay>
  );
}
