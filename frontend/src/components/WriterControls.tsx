interface WriterControlsProps {
  hasPending: boolean;
  onAccept: () => void;
  onRegenerate: () => void;
  disabled: boolean;
}

export default function WriterControls({ hasPending, onAccept, onRegenerate, disabled }: WriterControlsProps) {
  if (!hasPending) return null;

  return (
    <div className="flex gap-2 px-3 py-2 bg-surface border-t border-border">
      <button
        onClick={onAccept}
        disabled={disabled}
        className="flex-1 bg-green-700 hover:bg-green-600 text-white font-medium rounded-lg px-4 py-2 text-sm disabled:opacity-50 transition-colors"
      >
        Accept
      </button>
      <button
        onClick={onRegenerate}
        disabled={disabled}
        className="flex-1 bg-surface-alt hover:bg-border text-text font-medium rounded-lg px-4 py-2 text-sm disabled:opacity-50 transition-colors"
      >
        Regenerate
      </button>
    </div>
  );
}
