export type IconName =
  | "workspace"
  | "agents"
  | "extensions"
  | "tasks"
  | "memory"
  | "plus"
  | "arrow"
  | "activity"
  | "back"
  | "logout"
  | "server"
  | "tool"
  | "chevron"
  | "close"
  | "sparkles"
  | "search"
  | "file"
  | "chart"
  | "code"
  | "trash"
  | "shield"
  | "check";

const iconPaths: Record<
  IconName,
  string
> = {
  workspace:
    "M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-13ZM8 4v16M8 9h12",

  agents:
    "M8.5 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7-1a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM3.5 19c0-3 2.2-5 5-5s5 2 5 5m1.5-5c2.8 0 5 1.8 5 4.5",

  extensions:
    "M9 4H5a1 1 0 0 0-1 1v4m16 0V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4m6 0h4a1 1 0 0 0 1-1v-4M9 9h6v6H9V9Z",

  tasks:
    "M7 5h10M7 10h10M7 15h6M4 5h.01M4 10h.01M4 15h.01",

  memory:
    "M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3Zm0 0v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6m-14 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6",

  plus:
    "M12 5v14M5 12h14",

  arrow:
    "M5 12h14m-5-5 5 5-5 5",

  activity:
    "M4 13h4l2-7 4 12 2-5h4",

  back:
    "M19 12H5m6-6-6 6 6 6",

  logout:
    "M10 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4m5-4 4-3-4-3m4 3H9",

  server:
    "M5 4h14a1 1 0 0 1 1 1v5H4V5a1 1 0 0 1 1-1Zm-1 10h16v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-5Zm3-7h.01M7 17h.01",

  tool:
    "M14.5 6.5a4 4 0 0 0-5 5L4 17l3 3 5.5-5.5a4 4 0 0 0 5-5l-2.5 2.5-3-3 2.5-2.5Z",

  chevron:
    "m8 10 4 4 4-4",

  close:
    "M6 6l12 12M18 6 6 18",

  sparkles:
    "m12 3 1.2 3.1L16 7.3l-2.8 1.2L12 12l-1.2-3.5L8 7.3l2.8-1.2L12 3Zm6 9 .8 2.1L21 15l-2.2.9L18 18l-.8-2.1L15 15l2.2-.9L18 12ZM6 13l1 2.6L9.5 17 7 18.4 6 21l-1-2.6L2.5 17 5 15.6 6 13Z",

  search:
    "M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14Zm5-2 4 4",

  file:
    "M6 3h8l4 4v14H6V3Zm8 0v5h5M9 12h6M9 16h6",

  chart:
    "M5 19V10m7 9V5m7 14v-7M3 19h18",

  code:
    "m8 8-4 4 4 4m8-8 4 4-4 4m-5 2 2-12",

  trash:
    "M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5m4-5v5",

  shield:
    "M12 3 19 6v5c0 4.6-2.7 8-7 10-4.3-2-7-5.4-7-10V6l7-3Zm-3 9 2 2 4-5",

  check:
    "M5 12.5 9.2 17 19 7",
};

export function Icon({
  name,
  size = 18,
}: {
  name: IconName;
  size?: number;
}) {
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
      aria-hidden="true"
    >
      <path d={iconPaths[name]} />
    </svg>
  );
}

// =========================================================
// Helpers
// =========================================================
