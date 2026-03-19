import { useEffect, useState } from "react";
import Overlay from "./Overlay";
import { listLayouts, loadLayout, getLayout } from "../layout";

interface LayoutPickerProps {
  open: boolean;
  onClose: () => void;
}

export default function LayoutPicker({ open, onClose }: LayoutPickerProps) {
  const [layouts, setLayouts] = useState<string[]>([]);
  const [active, setActive] = useState(getLayout().name);
  const [loading, setLoading] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setActive(getLayout().name);
    listLayouts().then(setLayouts);
  }, [open]);

  async function handleSelect(name: string) {
    setLoading(name);
    try {
      await loadLayout(name);
      setActive(name);
      onClose();
    } catch {
      // Layout failed to load
    } finally {
      setLoading(null);
    }
  }

  return (
    <Overlay open={open} onClose={onClose} title="Layout">
      {layouts.length === 0 ? (
        <p className="text-sm text-text-muted">
          No layouts found in <code>layouts/</code> directory.
        </p>
      ) : (
        <div className="flex flex-col gap-1">
          {layouts.map((name) => (
            <button
              key={name}
              onClick={() => handleSelect(name)}
              disabled={loading !== null}
              className={`flex items-center justify-between px-3 py-2 rounded-lg text-left transition-colors ${
                name === active
                  ? "bg-accent/20 text-accent"
                  : "hover:bg-input-bg text-text"
              }`}
            >
              <span className="text-sm">{name}</span>
              {name === active && (
                <span className="text-xs text-accent/70">active</span>
              )}
              {loading === name && (
                <span className="text-xs text-text-muted">loading...</span>
              )}
            </button>
          ))}
        </div>
      )}
    </Overlay>
  );
}
