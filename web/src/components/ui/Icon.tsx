import type { ReactNode } from "react";

// One icon set (Visual standard, craft rules). Icons are drawn on a 16-unit grid and sized 1em,
// so they follow the text beside them; the stroke is the text's stem thickness in em (Atkinson /
// Plex: ≈ 0.085em at 400, 0.1em at 500, 0.115em at 600), so an icon never looks heavier or lighter
// than the word it sits next to, at any size.

export type IconName =
  | "close"
  | "chevron-right"
  | "chevron-down"
  | "info"
  | "check"
  | "cross"
  | "arrow-up"
  | "arrow-down"
  | "caret-up"
  | "caret-down"
  | "lock"
  | "search"
  | "download"
  | "link"
  | "warning"
  | "pin";

/** Stroke in grid units (1 unit = 1/16 em) for the weight of the adjacent text. */
const STROKE: Record<400 | 500 | 600, number> = { 400: 1.35, 500: 1.6, 600: 1.85 };

const PATHS: Record<IconName, ReactNode> = {
  close: <path d="M4 4l8 8M12 4l-8 8" />,
  cross: <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />,
  "chevron-right": <path d="M6 3.5L10.5 8 6 12.5" />,
  "chevron-down": <path d="M3.5 6L8 10.5 12.5 6" />,
  info: (
    <>
      <circle cx="8" cy="8" r="6.25" />
      <path d="M8 7.25v4M8 4.75v.01" />
    </>
  ),
  check: <path d="M3 8.5l3.5 3.5L13 4.5" />,
  "arrow-up": <path d="M8 13V3M4 7l4-4 4 4" />,
  "arrow-down": <path d="M8 3v10M4 9l4 4 4-4" />,
  "caret-up": <path d="M4 10l4-4 4 4" />,
  "caret-down": <path d="M4 6l4 4 4-4" />,
  lock: (
    <>
      <rect x="3.5" y="7.5" width="9" height="6" rx="1.5" />
      <path d="M5.5 7.5V5.5a2.5 2.5 0 0 1 5 0v2" />
    </>
  ),
  search: (
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5L13.5 13.5" />
    </>
  ),
  download: <path d="M8 2.5v8M4.5 7L8 10.5 11.5 7M3 13.5h10" />,
  link: <path d="M6.5 9.5l3-3M7 4.5l1-1a2.83 2.83 0 0 1 4 4l-1 1M9 11.5l-1 1a2.83 2.83 0 0 1-4-4l1-1" />,
  warning: <path d="M8 2.5l6.5 11h-13zM8 6.5v3M8 11.5v.01" />,
  pin: <path d="M6 2.5h4M7 2.5v4l-2.5 3h7L9 6.5v-4M8 9.5v4" />,
};

/**
 * An icon in the current text colour, sized to the current font size. Decorative by default
 * (aria-hidden); pass `label` when the icon alone carries meaning.
 */
export function Icon({ name, weight = 400, label, className = "" }: { name: IconName; weight?: 400 | 500 | 600; label?: string; className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={STROKE[weight]}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`inline-block shrink-0 align-[-0.125em] ${className}`}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
