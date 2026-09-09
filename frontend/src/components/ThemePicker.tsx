"use client";

import * as React from "react";

import { THEMES, themeStore, writeTheme } from "@/lib/theme";

/** Swatch menu in the header. Applies on hover so you can compare without committing. */
export function ThemePicker() {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  const theme = React.useSyncExternalStore(
    themeStore.subscribe,
    themeStore.getSnapshot,
    themeStore.getServerSnapshot,
  );

  React.useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) {
        setOpen(false);
        writeTheme(theme); // undo any hover preview
      }
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, theme]);

  const current = THEMES.find((t) => t.key === theme) ?? THEMES[0];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Colour theme: ${current.label}`}
        title="Colour theme"
        className="flex h-7 w-7 items-center justify-center rounded-md border transition-colors"
        style={{ borderColor: "var(--border-strong)", background: "var(--surface)" }}
      >
        <span
          className="h-3.5 w-3.5 rounded-full"
          style={{ background: "var(--accent)" }}
        />
      </button>

      {open ? (
        <div
          className="absolute right-0 z-40 mt-1.5 w-60 overflow-hidden rounded-lg border shadow-lg"
          style={{ background: "var(--surface)", borderColor: "var(--border-strong)" }}
          onMouseLeave={() => writeTheme(theme)}
        >
          <div
            className="border-b px-3 py-1.5 text-[11px] font-medium"
            style={{ borderColor: "var(--border)", color: "var(--text-subtle)" }}
          >
            Colour theme
          </div>
          {THEMES.map((t) => (
            <button
              key={t.key}
              type="button"
              onMouseEnter={() => document.documentElement.setAttribute("data-theme", t.key)}
              onClick={() => {
                writeTheme(t.key);
                setOpen(false);
              }}
              className="flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors hover:opacity-90"
              style={{ background: t.key === theme ? "var(--accent-soft)" : "transparent" }}
            >
              <span
                className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded-full ring-1"
                style={{ background: t.swatch, boxShadow: "inset 0 0 0 1px rgba(0,0,0,.15)" }}
              />
              <span className="min-w-0">
                <span className="block text-xs font-medium">{t.label}</span>
                <span className="block text-[11px]" style={{ color: "var(--text-subtle)" }}>
                  {t.note}
                </span>
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
