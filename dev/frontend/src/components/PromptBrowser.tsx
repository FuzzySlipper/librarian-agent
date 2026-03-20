import { useEffect, useState } from "react";
import MDEditor from "@uiw/react-md-editor";
import Overlay from "./Overlay";
import { listPersona, readPersona, writePersona, type PersonaFileInfo } from "../api";
import { listWritingStyles, readWritingStyle, writeWritingStyle, type WritingStyleInfo } from "../api";

interface PromptBrowserProps {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}

type Tab = "persona" | "writing";

export default function PromptBrowser({ open, onClose, onChanged }: PromptBrowserProps) {
  const [tab, setTab] = useState<Tab>("persona");
  const [personaFiles, setPersonaFiles] = useState<PersonaFileInfo[]>([]);
  const [styleFiles, setStyleFiles] = useState<WritingStyleInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<Tab>("persona");
  const [content, setContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    listPersona().then((data) => setPersonaFiles(data.files));
    listWritingStyles().then((data) => setStyleFiles(data.files));
  }, [open]);

  async function handleSelectPersona(path: string) {
    setLoading(true);
    try {
      const data = await readPersona(path);
      setSelected(path);
      setSelectedType("persona");
      setContent(data.content);
      setOriginalContent(data.content);
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectStyle(name: string) {
    setLoading(true);
    try {
      const data = await readWritingStyle(name);
      setSelected(name);
      setSelectedType("writing");
      setContent(data.content);
      setOriginalContent(data.content);
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    if (!selected) return;
    setSaving(true);
    try {
      if (selectedType === "persona") {
        await writePersona(selected, content);
        const data = await listPersona();
        setPersonaFiles(data.files);
      } else {
        await writeWritingStyle(selected, content);
        const data = await listWritingStyles();
        setStyleFiles(data.files);
      }
      setOriginalContent(content);
      onChanged();
    } finally {
      setSaving(false);
    }
  }

  function handleBack() {
    setSelected(null);
    setContent("");
    setOriginalContent("");
  }

  const isDirty = content !== originalContent;

  // Group persona files by directory
  const grouped = personaFiles.reduce<Record<string, PersonaFileInfo[]>>((acc, f) => {
    const dir = f.path.includes("/") ? f.path.split("/")[0] : "(root)";
    if (!acc[dir]) acc[dir] = [];
    acc[dir].push(f);
    return acc;
  }, {});

  const totalPersonaTokens = personaFiles.reduce((sum, f) => sum + f.tokens, 0);
  const totalStyleTokens = styleFiles.reduce((sum, f) => sum + f.tokens, 0);

  const tabClass = (t: Tab) =>
    `text-sm px-3 py-1.5 rounded-lg transition-colors ${
      tab === t ? "bg-accent text-white" : "text-text-muted hover:text-text"
    }`;

  // ── Editor view ──
  if (selected) {
    return (
      <Overlay open={open} onClose={onClose} title={selected}>
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <button
              onClick={handleBack}
              className="text-sm text-text-muted hover:text-text"
            >
              &larr; Back to list
            </button>
            <span className="text-xs text-text-muted">
              ~{Math.round(content.length / 4)} tokens
            </span>
          </div>
          {loading ? (
            <p className="text-text-muted">Loading...</p>
          ) : (
            <>
              <div data-color-mode="dark">
                <MDEditor
                  value={content}
                  onChange={(val) => setContent(val ?? "")}
                  height={400}
                  preview="edit"
                  visibleDragbar
                />
              </div>
              {isDirty && (
                <div className="flex gap-2 justify-end">
                  <button
                    onClick={() => setContent(originalContent)}
                    className="text-sm text-text-muted hover:text-text px-3 py-1.5"
                  >
                    Discard
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="text-sm bg-accent text-white rounded-lg px-4 py-1.5 disabled:opacity-50"
                  >
                    {saving ? "Saving..." : "Save"}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </Overlay>
    );
  }

  // ── List view ──
  return (
    <Overlay open={open} onClose={onClose} title="Prompts">
      <div className="flex flex-col gap-3">
        {/* Tab switcher */}
        <div className="flex gap-2">
          <button onClick={() => setTab("persona")} className={tabClass("persona")}>
            Persona
          </button>
          <button onClick={() => setTab("writing")} className={tabClass("writing")}>
            Writing Styles
          </button>
        </div>

        {tab === "persona" && (
          <>
            <div className="text-xs text-text-muted">
              {personaFiles.length} files · ~{Math.round(totalPersonaTokens / 1000)}k tokens total
            </div>
            {Object.entries(grouped).map(([dir, dirFiles]) => (
              <div key={dir}>
                <div className="text-xs font-medium text-text-muted uppercase tracking-wider mb-1">
                  {dir}
                </div>
                <div className="flex flex-col">
                  {dirFiles.map((f) => {
                    const name = f.path.includes("/")
                      ? f.path.split("/").slice(1).join("/")
                      : f.path;
                    return (
                      <button
                        key={f.path}
                        onClick={() => handleSelectPersona(f.path)}
                        className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-input-bg text-left transition-colors"
                      >
                        <span className="text-sm text-text">{name}</span>
                        <span className="text-xs text-text-muted">~{f.tokens} tok</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </>
        )}

        {tab === "writing" && (
          <>
            <div className="text-xs text-text-muted">
              {styleFiles.length} files · ~{Math.round(totalStyleTokens / 1000)}k tokens total
            </div>
            {styleFiles.length === 0 ? (
              <p className="text-sm text-text-muted">No writing style files yet.</p>
            ) : (
              <div className="flex flex-col">
                {styleFiles.map((f) => (
                  <button
                    key={f.name}
                    onClick={() => handleSelectStyle(f.name)}
                    className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-input-bg text-left transition-colors"
                  >
                    <span className="text-sm text-text">{f.name}</span>
                    <span className="text-xs text-text-muted">~{f.tokens} tok</span>
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </Overlay>
  );
}
