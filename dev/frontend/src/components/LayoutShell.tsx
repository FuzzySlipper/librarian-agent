import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { LayoutConfig, PanelConfig } from "../layout";
import type { Artifact } from "../artifacts";

interface LayoutShellProps {
  layout: LayoutConfig;
  chatContent: ReactNode;
  artifact: Artifact | null;
  backgroundImage?: string | null;
}

/** Format-specific styling classes for the artifact panel. */
const FORMAT_STYLES: Record<string, string> = {
  newspaper: "font-serif",
  letter: "font-serif italic",
  journal: "font-serif italic",
  texts: "font-mono text-[13px]",
  social: "text-[14px]",
  report: "font-mono text-[13px]",
  wanted: "font-serif text-center uppercase",
  prose: "",
};

function ArtifactPanel({ artifact, label }: { artifact: Artifact | null; label?: string }) {
  return (
    <div className="h-full flex flex-col bg-surface/50 border-x border-border/30">
      <div className="text-[11px] uppercase tracking-wider text-text-muted px-3 py-2 border-b border-border/30 bg-surface shrink-0 flex items-center justify-between">
        <span>{label || "Artifact"}</span>
        {artifact && (
          <span className="text-accent/70 normal-case tracking-normal">
            {artifact.format}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {artifact ? (
          <div
            className={`prose prose-invert prose-sm max-w-none leading-relaxed [&_p]:mb-3 [&_p:last-child]:mb-0 ${FORMAT_STYLES[artifact.format] || ""}`}
          >
            <ReactMarkdown>{artifact.content}</ReactMarkdown>
          </div>
        ) : (
          <p className="text-[13px] text-text-muted/50 italic leading-relaxed">
            No artifact loaded. Use <code className="text-accent/60 text-[12px]">/artifact</code> to generate one.
          </p>
        )}
      </div>
    </div>
  );
}

function PanelSlot({
  panel,
  artifact,
}: {
  panel: PanelConfig;
  artifact: Artifact | null;
}) {
  if (panel.type === "empty") {
    return <div className="h-full" />;
  }

  if (panel.type === "image") {
    return (
      <div
        className="h-full w-full"
        style={{
          backgroundImage: panel.src ? `url(${panel.src})` : undefined,
          backgroundSize: panel.fit || "cover",
          backgroundPosition: panel.position || "center center",
          backgroundRepeat: "no-repeat",
        }}
      />
    );
  }

  if (panel.type === "artifact") {
    return <ArtifactPanel artifact={artifact} label={panel.label} />;
  }

  if (panel.type === "panel") {
    return (
      <div className="h-full flex flex-col bg-surface/50 border-x border-border/30">
        {panel.label && (
          <div className="text-[11px] uppercase tracking-wider text-text-muted px-3 py-2 border-b border-border/30 bg-surface shrink-0">
            {panel.label}
          </div>
        )}
        <div className="flex-1 overflow-y-auto p-3">
          {panel.placeholder && (
            <p className="text-[13px] text-text-muted/60 italic leading-relaxed">
              {panel.placeholder}
            </p>
          )}
        </div>
      </div>
    );
  }

  // type === "chat" — handled by the parent
  return null;
}

export default function LayoutShell({ layout, chatContent, artifact, backgroundImage }: LayoutShellProps) {
  const isSingleColumn = layout.panels.length <= 1;

  const bgStyle: React.CSSProperties = backgroundImage
    ? {
        backgroundImage: `url(${backgroundImage})`,
        backgroundSize: "cover",
        backgroundPosition: "center center",
        backgroundRepeat: "no-repeat",
        backgroundAttachment: "fixed",
      }
    : {};

  const bgClass = backgroundImage ? "has-bg-image" : "";

  // Single column: no grid, just render chat directly
  if (isSingleColumn) {
    if (!backgroundImage) return <>{chatContent}</>;
    return (
      <div className={`h-dvh ${bgClass}`} style={bgStyle}>
        {chatContent}
      </div>
    );
  }

  return (
    <div
      className={`h-dvh ${bgClass}`}
      style={{
        display: "grid",
        gridTemplateColumns: layout.columns,
        ...bgStyle,
      }}
    >
      {layout.panels.map((panel) =>
        panel.type === "chat" ? (
          <div key={panel.name} className="h-dvh overflow-hidden">
            {chatContent}
          </div>
        ) : (
          <div key={panel.name} className="h-dvh overflow-hidden">
            <PanelSlot panel={panel} artifact={artifact} />
          </div>
        ),
      )}
    </div>
  );
}
