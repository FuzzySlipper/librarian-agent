import { useEffect, useState } from "react";
import MDEditor from "@uiw/react-md-editor";
import Overlay from "./Overlay";
import {
  listLayouts,
  loadLayout,
  getLayout,
  getBackground,
  setBackground,
  listBackgrounds,
  fetchLayoutContent,
  saveLayoutContent,
} from "../layout";

interface LayoutPickerProps {
  open: boolean;
  onClose: () => void;
}

type View = "list" | "edit" | "backgrounds";

export default function LayoutPicker({ open, onClose }: LayoutPickerProps) {
  const [view, setView] = useState<View>("list");
  const [layouts, setLayouts] = useState<string[]>([]);
  const [active, setActive] = useState(getLayout().name);
  const [loading, setLoading] = useState<string | null>(null);

  // Edit state
  const [editName, setEditName] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editOriginal, setEditOriginal] = useState("");
  const [saving, setSaving] = useState(false);

  // Background state
  const [backgrounds, setBackgrounds] = useState<{ filename: string; url: string }[]>([]);
  const [activeBg, setActiveBg] = useState<string | null>(getBackground());

  useEffect(() => {
    if (!open) return;
    setView("list");
    setActive(getLayout().name);
    setActiveBg(getBackground());
    listLayouts().then(setLayouts);
  }, [open]);

  async function handleSelect(name: string) {
    setLoading(name);
    try {
      await loadLayout(name);
      setActive(name);
    } catch {
      // Layout failed to load
    } finally {
      setLoading(null);
    }
  }

  async function handleEdit(name: string) {
    try {
      const content = await fetchLayoutContent(name);
      setEditName(name);
      setEditContent(content);
      setEditOriginal(content);
      setView("edit");
    } catch {
      // Failed to fetch
    }
  }

  async function handleSaveEdit() {
    setSaving(true);
    try {
      await saveLayoutContent(editName, editContent);
      setEditOriginal(editContent);
      // Reload if this is the active layout
      if (editName === active) {
        await loadLayout(editName);
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleOpenBackgrounds() {
    const bgs = await listBackgrounds();
    setBackgrounds(bgs);
    setView("backgrounds");
  }

  function handleSelectBg(url: string | null) {
    setBackground(url);
    setActiveBg(url);
  }

  const editDirty = editContent !== editOriginal;

  // ── Edit view ──
  if (view === "edit") {
    return (
      <Overlay open={open} onClose={onClose} title={`Edit: ${editName}`}>
        <div className="flex flex-col gap-3">
          <button
            onClick={() => setView("list")}
            className="text-sm text-text-muted hover:text-text self-start"
          >
            &larr; Back to layouts
          </button>
          <div data-color-mode="dark">
            <MDEditor
              value={editContent}
              onChange={(val) => setEditContent(val ?? "")}
              height={400}
              preview="edit"
              visibleDragbar
            />
          </div>
          {editDirty && (
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setEditContent(editOriginal)}
                className="text-sm text-text-muted hover:text-text px-3 py-1.5"
              >
                Discard
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={saving}
                className="text-sm bg-accent text-white rounded-lg px-4 py-1.5 disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          )}
        </div>
      </Overlay>
    );
  }

  // ── Background gallery ──
  if (view === "backgrounds") {
    return (
      <Overlay open={open} onClose={onClose} title="Background Image">
        <div className="flex flex-col gap-3">
          <button
            onClick={() => setView("list")}
            className="text-sm text-text-muted hover:text-text self-start"
          >
            &larr; Back to layouts
          </button>

          {/* Clear option */}
          <button
            onClick={() => handleSelectBg(null)}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
              !activeBg ? "bg-accent/20 ring-1 ring-accent/50" : "hover:bg-input-bg"
            }`}
          >
            <div className="w-16 h-12 rounded bg-surface-alt border border-border/50 flex items-center justify-center text-text-muted text-xs">
              none
            </div>
            <span className={`text-sm ${!activeBg ? "text-accent" : "text-text"}`}>No background</span>
            {!activeBg && <span className="text-xs text-accent/70 ml-auto">active</span>}
          </button>

          {backgrounds.length === 0 ? (
            <p className="text-sm text-text-muted">
              No images found. Add images to the <code className="text-accent/70">build/backgrounds/</code> directory.
            </p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {backgrounds.map((bg) => (
                <button
                  key={bg.filename}
                  onClick={() => handleSelectBg(bg.url)}
                  className={`rounded-lg overflow-hidden transition-all ${
                    activeBg === bg.url
                      ? "ring-2 ring-accent"
                      : "ring-1 ring-border/50 hover:ring-border"
                  }`}
                >
                  <div className="relative">
                    <img
                      src={bg.url}
                      alt={bg.filename}
                      className="w-full h-24 object-cover"
                    />
                    <div className="absolute bottom-0 inset-x-0 bg-black/60 px-2 py-1">
                      <span className="text-[10px] text-white truncate block">{bg.filename}</span>
                    </div>
                    {activeBg === bg.url && (
                      <div className="absolute top-1 right-1 bg-accent text-white text-[9px] px-1.5 py-0.5 rounded">
                        active
                      </div>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </Overlay>
    );
  }

  // ── Layout list (default view) ──
  return (
    <Overlay open={open} onClose={onClose} title="Layout & Background">
      <div className="flex flex-col gap-3">
        {/* Layouts section */}
        <div className="text-xs text-text-muted uppercase tracking-wider">Layouts</div>
        {layouts.length === 0 ? (
          <p className="text-sm text-text-muted">
            No layouts found in <code>layouts/</code> directory.
          </p>
        ) : (
          <div className="flex flex-col gap-1">
            {layouts.map((name) => (
              <div
                key={name}
                className={`flex items-center justify-between px-3 py-2 rounded-lg transition-colors ${
                  name === active
                    ? "bg-accent/20 text-accent"
                    : "hover:bg-input-bg text-text"
                }`}
              >
                <button
                  onClick={() => handleSelect(name)}
                  disabled={loading !== null}
                  className="flex-1 text-left"
                >
                  <span className="text-sm">{name}</span>
                  {name === active && (
                    <span className="text-xs text-accent/70 ml-2">active</span>
                  )}
                  {loading === name && (
                    <span className="text-xs text-text-muted ml-2">loading...</span>
                  )}
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); handleEdit(name); }}
                  className="text-xs text-text-muted hover:text-text px-2 py-1 rounded bg-surface-alt ml-2"
                >
                  edit
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Background section */}
        <div className="border-t border-border/50 pt-3 mt-1">
          <div className="flex items-center justify-between">
            <div className="text-xs text-text-muted uppercase tracking-wider">Background</div>
            <span className="text-xs text-text-muted">
              {activeBg ? activeBg.split("/").pop() : "none"}
            </span>
          </div>
          <button
            onClick={handleOpenBackgrounds}
            className="mt-2 text-sm text-accent hover:text-accent-hover"
          >
            Change background...
          </button>
        </div>
      </div>
    </Overlay>
  );
}
