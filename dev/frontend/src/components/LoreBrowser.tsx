import { useEffect, useState } from "react";
import MDEditor from "@uiw/react-md-editor";
import Overlay from "./Overlay";
import {
  listLore,
  readLore,
  writeLore,
  deleteLore,
  listLoreProjects,
  createLoreProject,
  switchProfile,
  type LoreFileInfo,
} from "../api";

interface LoreBrowserProps {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}

export default function LoreBrowser({ open, onClose, onChanged }: LoreBrowserProps) {
  const [files, setFiles] = useState<LoreFileInfo[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  // Project state
  const [projects, setProjects] = useState<string[]>([]);
  const [activeProject, setActiveProject] = useState<string | null>(null);
  const [showNewProject, setShowNewProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);

  // New file state
  const [newFileDir, setNewFileDir] = useState<string | null>(null);
  const [newFileName, setNewFileName] = useState("");

  useEffect(() => {
    if (!open) return;
    refresh();
  }, [open]);

  async function refresh() {
    const [loreData, projData] = await Promise.all([
      listLore(),
      listLoreProjects(),
    ]);
    setFiles(loreData.files);
    setCategories(loreData.categories);
    setActiveProject(loreData.active_project);
    setProjects(projData.projects);
  }

  async function handleSelectProject(name: string) {
    const loreSet = name === "(default)" ? "(default)" : name;
    await switchProfile({ lore_set: loreSet });
    onChanged();
    await refresh();
  }

  async function handleCreateProject() {
    if (!newProjectName.trim()) return;
    setCreatingProject(true);
    try {
      await createLoreProject(newProjectName.trim());
      setNewProjectName("");
      setShowNewProject(false);
      onChanged();
      await refresh();
    } finally {
      setCreatingProject(false);
    }
  }

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
      await refresh();
      onChanged();
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(path: string) {
    await deleteLore(path);
    if (selected === path) {
      setSelected(null);
      setContent("");
      setOriginalContent("");
    }
    await refresh();
    onChanged();
  }

  async function handleNewFile(dir: string) {
    if (!newFileName.trim()) return;
    const sanitized = newFileName.trim().toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-_]/g, "");
    if (!sanitized) return;
    const filename = sanitized.endsWith(".md") ? sanitized : `${sanitized}.md`;
    const path = dir === "(root)" ? filename : `${dir}/${filename}`;

    // Create the file with template content
    const template = dir === "characters"
      ? `# ${newFileName.trim()}\n\n**Role:** \n\n**Description:** \n\n**Background:** \n`
      : dir === "locations"
      ? `# ${newFileName.trim()}\n\n**Description:** \n\n**Notable features:** \n`
      : dir === "events"
      ? `# ${newFileName.trim()}\n\n**When:** \n\n**What happened:** \n\n**Consequences:** \n`
      : dir === "factions"
      ? `# ${newFileName.trim()}\n\n**Description:** \n\n**Goals:** \n\n**Key members:** \n`
      : `# ${newFileName.trim()}\n\n`;

    await writeLore(path, template);
    setNewFileDir(null);
    setNewFileName("");
    await refresh();
    onChanged();
    // Open the new file for editing
    handleSelect(path);
  }

  function handleBack() {
    setSelected(null);
    setContent("");
    setOriginalContent("");
  }

  const isDirty = content !== originalContent;
  const totalTokens = files.reduce((sum, f) => sum + f.tokens, 0);

  // Group files by directory, include empty categories
  const grouped: Record<string, LoreFileInfo[]> = {};
  // Seed empty categories
  for (const cat of categories) {
    grouped[cat] = [];
  }
  // Add root group
  grouped["(root)"] = [];
  // Distribute files
  for (const f of files) {
    const dir = f.path.includes("/") ? f.path.split("/")[0] : "(root)";
    if (!grouped[dir]) grouped[dir] = [];
    grouped[dir].push(f);
  }

  const hasProject = activeProject && activeProject !== "(default)";

  // ── File editor view ──
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
            <div className="flex items-center gap-3">
              <span className="text-xs text-text-muted">
                ~{Math.round(content.length / 4)} tokens
              </span>
              <button
                onClick={() => handleDelete(selected)}
                className="text-xs text-text-muted/50 hover:text-red-400"
                title="Delete file"
              >
                delete
              </button>
            </div>
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

  // ── File list view ──
  return (
    <Overlay open={open} onClose={onClose} title="Lore Files">
      <div className="flex flex-col gap-3">
        {/* Project selector */}
        <div className="flex items-center gap-2">
          <label className="text-xs text-text-muted uppercase tracking-wider shrink-0">Project</label>
          <select
            value={activeProject ?? "(default)"}
            onChange={(e) => handleSelectProject(e.target.value)}
            className="flex-1 bg-input-bg text-text border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-accent"
          >
            {projects.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
            {/* If active project isn't in list yet */}
            {activeProject && !projects.includes(activeProject) && (
              <option value={activeProject}>{activeProject}</option>
            )}
          </select>
          <button
            onClick={() => setShowNewProject(!showNewProject)}
            className="text-xs text-accent hover:text-accent-hover px-2 py-1.5 rounded-lg bg-surface-alt shrink-0"
            title="Create new lore project"
          >
            + New
          </button>
        </div>

        {/* New project form */}
        {showNewProject && (
          <div className="flex items-center gap-2 px-1">
            <input
              type="text"
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreateProject()}
              placeholder="project-name"
              className="flex-1 bg-input-bg text-text border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-accent"
              autoFocus
            />
            <button
              onClick={handleCreateProject}
              disabled={creatingProject || !newProjectName.trim()}
              className="text-xs bg-accent text-white rounded-lg px-3 py-1.5 disabled:opacity-50"
            >
              {creatingProject ? "..." : "Create"}
            </button>
            <button
              onClick={() => { setShowNewProject(false); setNewProjectName(""); }}
              className="text-xs text-text-muted hover:text-text px-2 py-1.5"
            >
              Cancel
            </button>
          </div>
        )}

        {/* Stats */}
        <div className="text-xs text-text-muted">
          {files.length} files · ~{Math.round(totalTokens / 1000)}k tokens total
          {hasProject && <span className="ml-1">· {activeProject}</span>}
        </div>

        {/* File groups */}
        {Object.entries(grouped).map(([dir, dirFiles]) => {
          // Skip root if empty
          if (dir === "(root)" && dirFiles.length === 0) return null;

          return (
            <div key={dir}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-text-muted uppercase tracking-wider">
                  {dir === "(root)" ? "general" : dir}
                </span>
                <button
                  onClick={() => {
                    if (newFileDir === dir) {
                      setNewFileDir(null);
                      setNewFileName("");
                    } else {
                      setNewFileDir(dir);
                      setNewFileName("");
                    }
                  }}
                  className="text-[10px] text-accent/60 hover:text-accent"
                  title={`New file in ${dir}`}
                >
                  + new file
                </button>
              </div>

              {/* New file inline form */}
              {newFileDir === dir && (
                <div className="flex items-center gap-2 px-3 py-1.5 mb-1">
                  <input
                    type="text"
                    value={newFileName}
                    onChange={(e) => setNewFileName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleNewFile(dir)}
                    placeholder="filename"
                    className="flex-1 bg-input-bg text-text border border-border rounded px-2 py-1 text-sm focus:outline-none focus:border-accent"
                    autoFocus
                  />
                  <button
                    onClick={() => handleNewFile(dir)}
                    disabled={!newFileName.trim()}
                    className="text-xs text-accent hover:text-accent-hover disabled:opacity-30"
                  >
                    create
                  </button>
                  <button
                    onClick={() => { setNewFileDir(null); setNewFileName(""); }}
                    className="text-xs text-text-muted hover:text-text"
                  >
                    ×
                  </button>
                </div>
              )}

              <div className="flex flex-col">
                {dirFiles.length === 0 && newFileDir !== dir && (
                  <span className="text-xs text-text-muted/40 px-3 py-1.5 italic">empty</span>
                )}
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
          );
        })}
      </div>
    </Overlay>
  );
}
