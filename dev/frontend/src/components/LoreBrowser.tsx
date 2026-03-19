import { useEffect, useState } from "react";
import MDEditor from "@uiw/react-md-editor";
import Overlay from "./Overlay";
import { listLore, readLore, writeLore, type LoreFileInfo } from "../api";

interface LoreBrowserProps {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}

export default function LoreBrowser({ open, onClose, onChanged }: LoreBrowserProps) {
  const [files, setFiles] = useState<LoreFileInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    listLore().then((data) => setFiles(data.files));
  }, [open]);

  async function handleSelect(path: string) {
    setLoading(true);
    try {
      const data = await readLore(path);
      setSelected(path);
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
      await writeLore(selected, content);
      setOriginalContent(content);
      // Refresh file list to update token counts
      const data = await listLore();
      setFiles(data.files);
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
  const totalTokens = files.reduce((sum, f) => sum + f.tokens, 0);

  // Group files by directory
  const grouped = files.reduce<Record<string, LoreFileInfo[]>>((acc, f) => {
    const dir = f.path.includes("/") ? f.path.split("/")[0] : "(root)";
    if (!acc[dir]) acc[dir] = [];
    acc[dir].push(f);
    return acc;
  }, {});

  return (
    <Overlay open={open} onClose={onClose} title={selected ? selected : "Lore Files"}>
      {selected ? (
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
      ) : (
        <div className="flex flex-col gap-3">
          <div className="text-xs text-text-muted">
            {files.length} files · ~{Math.round(totalTokens / 1000)}k tokens total
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
                      onClick={() => handleSelect(f.path)}
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
        </div>
      )}
    </Overlay>
  );
}
