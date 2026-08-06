'use client';

import type { ReactNode } from 'react';

/**
 * Custom, original glyph set for Sovereign-Agentic-AI.
 * Hand-drawn stroke icons (no lucide/heroicons copies) so the brand looks
 * unique: same stroke language (1.7px, rounded caps), distinctive geometry.
 */

type IconProps = { size?: number; className?: string };

function Svg({ size = 18, className, children }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

/** Hub-and-spoke orchestrator: one brain routes to many workers. */
export function OrchestratorIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="2.4" />
      <circle cx="4.5" cy="5.5" r="1.8" />
      <circle cx="19.5" cy="5.5" r="1.8" />
      <circle cx="4.5" cy="18.5" r="1.8" />
      <circle cx="19.5" cy="18.5" r="1.8" />
      <path d="M6.1 6.8l4.1 4.1" />
      <path d="M17.9 6.8l-4.1 4.1" />
      <path d="M6.1 17.2l4.1-4.1" />
      <path d="M17.9 17.2l-4.1-4.1" />
    </Svg>
  );
}

/** Agentic terminal: code brackets with a blinking cursor run-line. */
export function TerminalCodeIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3.5 5.5h17a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-17a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1z" />
      <path d="M7 9l-2 2.2 2 2.2" />
      <path d="M11 13.4h5" />
      <path d="M8.5 4v3M15.5 4v3" opacity="0.55" />
    </Svg>
  );
}

/** Agent X core: hexagonal all-in-one mind with a bold "X" + spark. */
export function AgentXIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 2.8l7.2 4.2v8.2l-7.2 4.2-7.2-4.2V7z" />
      <path d="M9 9l6 6M15 9l-6 6" />
      <path d="M12 12l3.4-1.2M12 12l-1.8-3" opacity="0.7" />
    </Svg>
  );
}

/** Local engine: GPU chip with an on-device down-beacon. */
export function LocalEngineIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="6" y="6" width="12" height="12" rx="2.5" />
      <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
      <path d="M9 2.5v2.5M15 2.5v2.5M9 19v2.5M15 19v2.5M2.5 9H5M2.5 15H5M19 9h2.5M19 15h2.5" />
      <path d="M12 4.6c0 1.8 1.2 3 1.2 4.6" opacity="0.7" />
    </Svg>
  );
}

/** Knowledge graph: linked node web with a diamond hub. */
export function GraphWebIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 4.5l2 3-2 3-2-3z" />
      <circle cx="6" cy="15.5" r="2.2" />
      <circle cx="18" cy="15.5" r="2.2" />
      <path d="M11.2 9.6l-3.6 4.2" />
      <path d="M12.8 9.6l3.6 4.2" />
      <path d="M7.4 13.7l1.6 1.6M16.6 13.7l-1.6 1.6" opacity="0.6" />
    </Svg>
  );
}

/** Workspaces: stacked isolated panes with their own content window. */
export function WorkspacePaneIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3" y="4.5" width="12" height="9.5" rx="1.8" />
      <rect x="9" y="10" width="12" height="9.5" rx="1.8" />
      <circle cx="5.6" cy="7" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="11.6" cy="12.5" r="0.9" fill="currentColor" stroke="none" opacity="0.7" />
    </Svg>
  );
}

/** Vision lens: eye inside a ring, on-device sight. */
export function VisionLensIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.2" />
      <circle cx="12" cy="12" r="3.4" />
      <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
      <path d="M3.8 12h2.2M18 12h2.2M12 3.8v2.2M12 18v2.2" opacity="0.7" />
    </Svg>
  );
}

/** Art forge: canvas + brush stroke producing an image. */
export function ArtForgeIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3.5 4h17a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1h-17a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
      <circle cx="7.2" cy="8.8" r="1.3" />
      <path d="M6 15l3.4-4.2L13 15zM12.5 15l3-5 2.6 5z" opacity="0.9" />
    </Svg>
  );
}

/** ReAct loop: gear arrow that loops tools back into reasoning. */
export function ReactLoopIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M17.6 8.4l1.8-1.8" />
      <path d="M18.9 12h2.4" />
      <path d="M17.6 15.6l1.8 1.8" />
      <path d="M12 18.9v2.4" />
      <path d="M6.4 15.6l-1.8 1.8" />
      <path d="M2.7 12h2.4" />
      <path d="M6.4 8.4L4.6 6.6" />
      <path d="M12 5.1V2.7" />
    </Svg>
  );
}

/** Memory matrix: vector store column with embedding waves. */
export function MemoryMatrixIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3.5l7 2.5v12l-7 2.5-7-2.5V6z" />
      <path d="M5 6l7 2.5 7-2.5" />
      <path d="M12 8.5v11" />
      <path d="M8.2 12.6c1.2 1 2.4 1 3.8 0 1.4-1 2.6-1 3.8 0" opacity="0.8" />
    </Svg>
  );
}

/** Sandbox shield: locked scope around the computer agent. */
export function SandboxShieldIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3l7 2.4v5.3c0 4.4-3 7.7-7 9.3-4-1.6-7-4.9-7-9.3V5.4z" />
      <rect x="9.6" y="9.8" width="4.8" height="4.6" rx="0.9" />
      <path d="M12 9.8V8.6a1.5 1.5 0 0 1 0-3" opacity="0.8" />
    </Svg>
  );
}

/** Data lake: dataset layers feeding a droplet of knowledge. */
export function DataLakeIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 7.5c0-1.4 3.6-2.5 8-2.5s8 1.1 8 2.5-3.6 2.5-8 2.5-8-1.1-8-2.5z" />
      <path d="M4 7.5v4c0 1.4 3.6 2.5 8 2.5" opacity="0.8" />
      <path d="M20 7.5v4c0 1.4-3.6 2.5-8 2.5" opacity="0.6" />
      <path d="M12 14c0 2-2.6 3.2-2.6 5a2.6 2.6 0 0 0 5.2 0c0-1.8-2.6-3-2.6-5z" />
    </Svg>
  );
}

/** Cloud bridge: optional cloud fallback with a plug-in link. */
export function CloudBridgeIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M7.5 17.5h9a4 4 0 0 0 .6-8A5.4 5.4 0 0 0 6.3 9.6a3.6 3.6 0 0 0 1.2 7.9z" />
      <path d="M12 10v3.4M10.2 12.6l3.6 1.8" opacity="0.9" />
    </Svg>
  );
}

/** Hub download: fetch a model from Hugging Face into local storage. */
export function HubDownloadIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3v10" />
      <path d="M8.5 9.5L12 13l3.5-3.5" />
      <path d="M4.5 15.5v2a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-2" />
    </Svg>
  );
}

/** Pulsing live metric heart-beat line. */
export function PulseLineIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M2.5 12h4l2.2-5 3.4 10 2.6-5h6.8" />
    </Svg>
  );
}
