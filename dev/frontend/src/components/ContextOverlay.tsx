import Overlay from "./Overlay";
import ContextMeter from "./ContextMeter";
import type { Status } from "../types";

interface ContextOverlayProps {
  open: boolean;
  onClose: () => void;
  status: Status | null;
}

export default function ContextOverlay({ open, onClose, status }: ContextOverlayProps) {
  return (
    <Overlay open={open} onClose={onClose} title="Context Usage">
      {status?.status === "ready" ? (
        <div className="flex flex-col gap-4">
          <ContextMeter status={status} />
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="bg-input-bg rounded-lg p-3">
              <div className="text-text-muted text-xs mb-1">Persona</div>
              <div>{status.persona}</div>
            </div>
            <div className="bg-input-bg rounded-lg p-3">
              <div className="text-text-muted text-xs mb-1">Lore Set</div>
              <div>{status.lore_set}</div>
            </div>
            <div className="bg-input-bg rounded-lg p-3">
              <div className="text-text-muted text-xs mb-1">Writing Style</div>
              <div>{status.writing_style}</div>
            </div>
            <div className="bg-input-bg rounded-lg p-3">
              <div className="text-text-muted text-xs mb-1">Model</div>
              <div className="text-xs break-all">{status.model}</div>
            </div>
            <div className="bg-input-bg rounded-lg p-3">
              <div className="text-text-muted text-xs mb-1">Conversation</div>
              <div>{status.conversation_turns} turns</div>
            </div>
            <div className="bg-input-bg rounded-lg p-3">
              <div className="text-text-muted text-xs mb-1">Lore Files</div>
              <div>{status.lore_files} loaded</div>
            </div>
          </div>
        </div>
      ) : (
        <p className="text-text-muted">System not ready</p>
      )}
    </Overlay>
  );
}
