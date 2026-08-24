"use client";

import * as React from "react";

import { api } from "@/lib/api";
import { useAsync, useDebounced } from "@/lib/hooks";
import { Input, cx } from "@/components/ui";
import type { ReferenceItem } from "@/lib/types";

/**
 * Typeahead over one taxonomy domain.
 *
 * Searches aliases as well as names, so typing "sinker" finds Single Jersey and "process
 * house" finds fabric dyeing — the words suppliers actually use. Free text is not accepted:
 * §11's first project killer is unmatchable capability data, so the value that leaves this
 * component is always a real taxonomy code.
 */
export function TaxonomyPicker({
  domain,
  value,
  onChange,
  placeholder,
  required,
}: {
  domain: string;
  value: string;
  onChange: (code: string, item: ReferenceItem | null) => void;
  placeholder?: string;
  required?: boolean;
}) {
  const [query, setQuery] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const [highlight, setHighlight] = React.useState(0);
  const debounced = useDebounced(query, 200);
  const containerRef = React.useRef<HTMLDivElement>(null);

  const { data } = useAsync(
    () =>
      api.get<ReferenceItem[]>("/master-data/items", {
        domain,
        search: debounced || undefined,
      }),
    [domain, debounced],
  );

  const options = (data ?? []).slice(0, 40);
  const selected = options.find((o) => o.code === value);

  React.useEffect(() => {
    function onClickAway(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, []);

  function choose(item: ReferenceItem) {
    onChange(item.code, item);
    setQuery("");
    setOpen(false);
  }

  return (
    <div ref={containerRef} className="relative">
      <Input
        value={open ? query : selected?.name ?? value}
        placeholder={placeholder ?? "Start typing…"}
        required={required && !value}
        onFocus={() => {
          setOpen(true);
          setQuery("");
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setHighlight(0);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (!open) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setHighlight((h) => Math.min(h + 1, options.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlight((h) => Math.max(h - 1, 0));
          } else if (e.key === "Enter" && options[highlight]) {
            e.preventDefault();
            choose(options[highlight]);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />

      {open ? (
        <div
          className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-md border shadow-lg"
          style={{ background: "var(--surface)", borderColor: "var(--border-strong)" }}
        >
          {options.length === 0 ? (
            <p className="px-3 py-2 text-xs" style={{ color: "var(--text-subtle)" }}>
              Nothing matches. Ask a Super Admin to add it — we do not store free text here,
              because a value nobody can filter on is invisible to the matching engine.
            </p>
          ) : (
            options.map((item, index) => (
              <button
                key={item.id}
                type="button"
                onMouseEnter={() => setHighlight(index)}
                onClick={() => choose(item)}
                className={cx("block w-full px-3 py-1.5 text-left text-sm")}
                style={{
                  background: index === highlight ? "var(--accent-soft)" : "transparent",
                  color: index === highlight ? "var(--accent)" : "var(--text)",
                }}
              >
                <span>{item.name}</span>
                {item.aliases?.length ? (
                  <span className="ml-2 text-[11px]" style={{ color: "var(--text-subtle)" }}>
                    {item.aliases.slice(0, 3).join(", ")}
                  </span>
                ) : null}
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
