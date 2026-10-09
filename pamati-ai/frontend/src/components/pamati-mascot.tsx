export function PamatiMascot({ compact = false }: { compact?: boolean }) {
  return <svg className={compact ? "pamati-mascot compact" : "pamati-mascot"} viewBox="0 0 180 190" aria-hidden="true">
    <ellipse cx="90" cy="174" rx="65" ry="10" fill="#ddd8ff" />
    <path d="M57 160Q57 119 90 119Q123 119 123 160" fill="#eef0ff" stroke="#aaa5ff" strokeWidth="3" />
    <path d="M78 143C69 132 56 148 90 165C124 148 111 132 102 143L90 153Z" fill="#7957ff" />
    <path d="M90 36V22" stroke="#9c91f6" strokeWidth="5" /><circle cx="90" cy="18" r="7" fill="#c8c2ff" />
    <rect x="23" y="64" width="18" height="40" rx="9" fill="#c1bcff" /><rect x="139" y="64" width="18" height="40" rx="9" fill="#c1bcff" />
    <rect x="36" y="35" width="108" height="92" rx="42" fill="#f8f8ff" stroke="#c8c2ff" strokeWidth="3" />
    <rect x="48" y="53" width="84" height="58" rx="26" fill="#15214e" />
    <ellipse cx="71" cy="78" rx="6" ry="9" fill="#57d5ff" /><ellipse cx="109" cy="78" rx="6" ry="9" fill="#57d5ff" />
    <path d="M80 94Q90 103 100 94" fill="none" stroke="#57d5ff" strokeWidth="3" strokeLinecap="round" />
  </svg>;
}

export function PamatiMark() {
  return <svg className="pamati-mark" viewBox="0 0 40 40" aria-hidden="true"><path d="M18 7C8 0 2 15 7 20C0 27 9 39 18 33M22 7C32 0 38 15 33 20C40 27 31 39 22 33" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" /><path d="M20 30L10 20C3 10 16 8 20 15C24 8 37 10 30 20Z" fill="none" stroke="currentColor" strokeWidth="2.5" /></svg>;
}

export function WorkspaceIcon({ section }: { section: string }) {
  const paths: Record<string, string> = {
    conversations: "M3 10L12 3L21 10V21H15V14H9V21H3Z",
    chat: "M4 4H20V16H10L4 21Z",
    trends: "M4 20V12M10 20V5M16 20V9M22 20H2",
    resources: "M5 3H15L20 8V21H5ZM14 3V9H20M8 13H16M8 17H14",
    support: "M12 21L3 12C-2 3 8 0 12 7C16 0 26 3 21 12Z",
    "check-ins": "M5 5H19V21H5ZM8 2V8M16 2V8M5 10H19M9 15L11 17L16 12",
    privacy: "M12 2L21 6V12Q21 19 12 23Q3 19 3 12V6ZM8 12L11 15L17 9",
  };
  return <svg className="workspace-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[section] ?? "M4 4H10V10H4ZM14 4H20V10H14ZM4 14H10V20H4ZM14 14H20V20H14Z"} /></svg>;
}
