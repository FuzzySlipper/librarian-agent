import { useEffect, useState } from "react";
import Overlay from "./Overlay";
import { getProfiles, switchProfile } from "../api";
import type { Profiles } from "../types";

interface ProfilePickerProps {
  open: boolean;
  onClose: () => void;
  onSwitched: () => void;
}

export default function ProfilePicker({ open, onClose, onSwitched }: ProfilePickerProps) {
  const [profiles, setProfiles] = useState<Profiles | null>(null);
  const [persona, setPersona] = useState("");
  const [loreSet, setLoreSet] = useState("");
  const [style, setStyle] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    getProfiles().then((p) => {
      setProfiles(p);
      setPersona(p.active_persona);
      setLoreSet(p.active_lore);
      setStyle(p.active_writing_style);
    });
  }, [open]);

  async function handleSave() {
    setSaving(true);
    try {
      await switchProfile({
        persona,
        lore_set: loreSet,
        writing_style: style,
      });
      onSwitched();
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Overlay open={open} onClose={onClose} title="Profile">
      {profiles ? (
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-sm text-text-muted">Persona</span>
            <select
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              className="bg-input-bg text-text border border-border rounded-lg px-3 py-2"
            >
              {profiles.personas.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-sm text-text-muted">Lore Set</span>
            <select
              value={loreSet}
              onChange={(e) => setLoreSet(e.target.value)}
              className="bg-input-bg text-text border border-border rounded-lg px-3 py-2"
            >
              {profiles.lore_sets.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-sm text-text-muted">Writing Style</span>
            <select
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              className="bg-input-bg text-text border border-border rounded-lg px-3 py-2"
            >
              {profiles.writing_styles.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>

          <button
            onClick={handleSave}
            disabled={saving}
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
