interface RoleplayControlsProps {
  hasMessages: boolean;
  onRegenerate: () => void;
  onDeleteLast: () => void;
  disabled: boolean;
}

export default function RoleplayControls({ hasMessages, onRegenerate, onDeleteLast, disabled }: RoleplayControlsProps) {
  if (!hasMessages) return null;

  return (
    <div className="flex gap-2 px-3 py-2 bg-surface border-t border-border">
      <button
        onClick={onRegenerate}
        disabled={disabled}
        className="flex-1 bg-surface-alt hover:bg-border text-text font-medium rounded-lg px-4 py-2 text-sm disabled:opacity-50 transition-colors"
      >
        Regenerate
      </button>
      <button
        onClick={onDeleteLast}
        disabled={disabled}
        className="flex-1 bg-surface-alt hover:bg-border text-text-muted font-medium rounded-lg px-4 py-2 text-sm disabled:opacity-50 transition-colors"
      >
        Delete Last
      </button>
    </div>
  );
}
