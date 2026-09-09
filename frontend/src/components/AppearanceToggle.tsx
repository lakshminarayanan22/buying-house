"use client";

import * as React from "react";

import { APPEARANCES, appearanceStore, writeAppearance } from "@/lib/theme";

/** Three-state appearance control in the header. */
export function AppearanceToggle() {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  const appearance = React.useSyncExternalStore(
    appearanceStore.subscribe,
    appearanceStore.getSnapshot,
    appearanceStore.getServerSnapshot,
  );

  React.useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const current = APPEARANCES.find((a) => a.key === appearance) ?? APPEARANCES[0];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Appearance: ${current.label}`}
        title={`Appearance — ${current.label}`}
        className="flex h-7 w-7 items-center justify-center rounded-md border transition-colors"
        style={{ borderColor: "var(--border-strong)", background: "var(--surface-2)" }}
      >
        {/* Half-filled disc: the universal "how light is this" mark. */}
        <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden>
          <circle cx="8" cy="8" r="6" fill="none" stroke="var(--text-muted)" strokeWidth="1.4" />
          <path d="M8 2a6 6 0 0 0 0 12z" fill="var(--text-muted)" />
        </svg>
      </button>

      {open ? (
        <div
          className="absolute right-0 z-40 mt-1.5 w-56 overflow-hidden rounded-lg border shadow-xl"
          style={{ background: "var(--surface)", borderColor: "var(--border-strong)" }}
        >
          <div className="micro border-b px-3 py-1.5" style={{ borderColor: "var(--border)" }}>
            Appearance
          </div>
          {APPEARANCES.map((a) => (
            <button
              key={a.key}
              type="button"
              onClick={() => {
                writeAppearance(a.key);
                setOpen(false);
              }}
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
              style={{ background: a.key === appearance ? "var(--accent-soft)" : "transparent" }}
            >
              <span className="min-w-0">
                <span
                  className="block text-xs font-medium"
                  style={{ color: a.key === appearance ? "var(--accent)" : "var(--text)" }}
                >
                  {a.label}
                </span>
                <span className="block text-[11px]" style={{ color: "var(--text-subtle)" }}>
                  {a.hint}
                </span>
              </span>
              {a.key === appearance ? (
                <span style={{ color: "var(--accent)" }}>✓</span>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
