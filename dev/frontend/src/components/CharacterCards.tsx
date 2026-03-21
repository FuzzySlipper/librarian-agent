import { useEffect, useRef, useState } from "react";
import Overlay from "./Overlay";
import {
  listCharacterCards,
  readCharacterCard,
  createCharacterCard,
  updateCharacterCard,
  deleteCharacterCard,
  activateCharacterCards,
  importCharacterCard,
  type CharacterCardSummary,
  type CharacterCard,
} from "../api";

interface CharacterCardsProps {
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
  portraits: { filename: string; url: string }[];
}

const EMPTY_CARD: CharacterCard = {
  name: "",
  portrait: "",
  personality: "",
  description: "",
  scenario: "",
  greeting: "",
};

export default function CharacterCards({ open, onClose, onChanged, portraits }: CharacterCardsProps) {
  const [cards, setCards] = useState<CharacterCardSummary[]>([]);
  const [activeAi, setActiveAi] = useState<string | null>(null);
  const [activeUser, setActiveUser] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null); // filename or "__new__"
  const [form, setForm] = useState<CharacterCard>(EMPTY_CARD);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    refresh();
  }, [open]);

  async function refresh() {
    const data = await listCharacterCards();
    setCards(data.cards);
    setActiveAi(data.active_ai);
    setActiveUser(data.active_user);
  }

  async function handleEdit(filename: string) {
    const card = await readCharacterCard(filename);
    setForm({ ...EMPTY_CARD, ...card });
    setEditing(filename);
    setError(null);
  }

  function handleNew() {
    setForm({ ...EMPTY_CARD });
    setEditing("__new__");
    setError(null);
  }

  async function handleSave() {
    if (!form.name.trim()) {
      setError("Name is required");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editing === "__new__") {
        await createCharacterCard(form);
      } else if (editing) {
        await updateCharacterCard(editing, form);
      }
      await refresh();
      onChanged();
      setEditing(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(filename: string) {
    await deleteCharacterCard(filename);
    await refresh();
    onChanged();
  }

  async function handleActivate(role: "ai" | "user", filename: string | null) {
    if (role === "ai") {
      await activateCharacterCards({ ai_character: filename ?? "" });
    } else {
      await activateCharacterCards({ user_character: filename ?? "" });
    }
    await refresh();
    onChanged();
  }

  const inputClass =
    "w-full bg-input-bg text-text border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent";

  // ── Edit form ──
  if (editing) {
    const isNew = editing === "__new__";
    return (
      <Overlay open={open} onClose={onClose} title={isNew ? "New Character" : `Edit: ${form.name || editing}`}>
        <div className="flex flex-col gap-3">
          <button onClick={() => setEditing(null)} className="text-sm text-text-muted hover:text-text self-start">
            &larr; Back to list
          </button>

          <div>
            <label className="text-xs text-text-muted uppercase tracking-wider">Name</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Character name"
              className={inputClass}
            />
          </div>

          <div>
            <label className="text-xs text-text-muted uppercase tracking-wider">Portrait</label>
            {portraits.length > 0 ? (
              <div className="flex flex-wrap gap-2 mt-1">
                {portraits.map((p) => (
                  <button
                    key={p.filename}
                    onClick={() => setForm({ ...form, portrait: p.filename })}
                    className={`w-12 h-12 rounded-full overflow-hidden ring-2 transition-all ${
                      form.portrait === p.filename ? "ring-accent" : "ring-transparent hover:ring-border"
                    }`}
                  >
                    <img src={p.url} alt={p.filename} className="w-full h-full object-cover" />
                  </button>
                ))}
                {form.portrait && (
                  <button
                    onClick={() => setForm({ ...form, portrait: "" })}
                    className="text-[10px] text-text-muted hover:text-text self-center"
                  >
                    clear
                  </button>
                )}
              </div>
            ) : (
              <input
                type="text"
                value={form.portrait}
                onChange={(e) => setForm({ ...form, portrait: e.target.value })}
                placeholder="filename.png (in build/portraits/)"
                className={inputClass}
              />
            )}
          </div>

          <div>
            <label className="text-xs text-text-muted uppercase tracking-wider">Personality</label>
            <textarea
              value={form.personality}
              onChange={(e) => setForm({ ...form, personality: e.target.value })}
              placeholder="Core personality traits, speech patterns, mannerisms..."
              rows={3}
              className={`${inputClass} resize-y`}
            />
          </div>

          <div>
            <label className="text-xs text-text-muted uppercase tracking-wider">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Physical appearance, typical clothing, notable features..."
              rows={3}
              className={`${inputClass} resize-y`}
            />
          </div>

          <div>
            <label className="text-xs text-text-muted uppercase tracking-wider">Scenario</label>
            <textarea
              value={form.scenario}
              onChange={(e) => setForm({ ...form, scenario: e.target.value })}
              placeholder="The setting/situation for this character (optional)..."
              rows={2}
              className={`${inputClass} resize-y`}
            />
          </div>

          <div>
            <label className="text-xs text-text-muted uppercase tracking-wider">Greeting</label>
            <textarea
              value={form.greeting}
              onChange={(e) => setForm({ ...form, greeting: e.target.value })}
              placeholder="Opening message when starting a new chat..."
              rows={3}
              className={`${inputClass} resize-y`}
            />
          </div>

          {error && <p className="text-sm text-red-400">{error}</p>}

          <div className="flex gap-2 justify-end pt-2">
            <button onClick={() => setEditing(null)} className="text-sm text-text-muted hover:text-text px-3 py-1.5">
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="text-sm bg-accent text-white rounded-lg px-4 py-1.5 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      </Overlay>
    );
  }

  // ── Card list ──
  return (
    <Overlay open={open} onClose={onClose} title="Character Cards">
      <div className="flex flex-col gap-4">
        {/* Active character assignments */}
        <div className="flex flex-col gap-2">
          <div className="text-xs text-text-muted uppercase tracking-wider">Active Characters</div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-text min-w-[80px]">AI plays</span>
            <select
              value={activeAi ?? ""}
              onChange={(e) => handleActivate("ai", e.target.value || null)}
              className="flex-1 bg-input-bg text-text border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-accent"
            >
              <option value="">(none)</option>
              {cards.map((c) => (
                <option key={c.filename} value={c.filename}>{c.name}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-text min-w-[80px]">User plays</span>
            <select
              value={activeUser ?? ""}
              onChange={(e) => handleActivate("user", e.target.value || null)}
              className="flex-1 bg-input-bg text-text border border-border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-accent"
            >
              <option value="">(none)</option>
              {cards.map((c) => (
                <option key={c.filename} value={c.filename}>{c.name}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Card list */}
        <div>
          <div className="text-xs text-text-muted uppercase tracking-wider mb-2">Characters</div>
          {cards.length === 0 ? (
            <p className="text-sm text-text-muted">No character cards yet.</p>
          ) : (
            <div className="flex flex-col gap-1.5">
              {cards.map((c) => (
                <div
                  key={c.filename}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-lg bg-input-bg/50 border ${
                    c.filename === activeAi || c.filename === activeUser
                      ? "border-accent/40"
                      : "border-border/50"
                  }`}
                >
                  {c.portrait ? (
                    <img
                      src={`/portraits/${c.portrait}`}
                      alt=""
                      className="w-10 h-10 rounded-full object-cover ring-1 ring-border shrink-0"
                    />
                  ) : (
                    <div className="w-10 h-10 rounded-full bg-surface-alt ring-1 ring-border shrink-0 flex items-center justify-center text-text-muted text-xs">
                      ?
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-text">{c.name}</div>
                    <div className="text-[10px] text-text-muted">
                      {c.filename === activeAi && <span className="text-accent">AI character</span>}
                      {c.filename === activeAi && c.filename === activeUser && " · "}
                      {c.filename === activeUser && <span className="text-accent">User character</span>}
                    </div>
                  </div>
                  <div className="flex gap-1.5 shrink-0">
                    <button
                      onClick={() => handleEdit(c.filename)}
                      className="text-xs text-text-muted hover:text-text px-2 py-1 rounded bg-surface-alt"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(c.filename)}
                      className="text-xs text-text-muted hover:text-red-400 px-2 py-1 rounded bg-surface-alt"
                    >
                      Del
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex gap-3 items-center">
          <button
            onClick={handleNew}
            className="text-sm text-accent hover:text-accent-hover"
          >
            + New Character
          </button>
          <span className="text-text-muted/30">|</span>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={importing}
            className="text-sm text-accent hover:text-accent-hover disabled:opacity-50"
          >
            {importing ? "Importing..." : "Import ST Card"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".png"
            className="hidden"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              setImporting(true);
              setError(null);
              try {
                await importCharacterCard(file);
                await refresh();
                // Refresh portraits list too
                onChanged();
              } catch (err) {
                setError(err instanceof Error ? err.message : "Import failed");
              } finally {
                setImporting(false);
                // Reset input so the same file can be re-selected
                if (fileInputRef.current) fileInputRef.current.value = "";
              }
            }}
          />
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}
      </div>
    </Overlay>
  );
}
