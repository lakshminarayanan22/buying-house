"use client";

import * as React from "react";

import { Badge, Button } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { titleCase } from "@/lib/format";
import type { DocRow, ExtractionStatus } from "@/lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

/**
 * Whether the assistant can read this file, and why not when it can't.
 *
 * A file that reads fine says nothing — a badge on every row would be noise. Only the
 * cases that need a human: still working, or never going to work. A scanned brochure is
 * the one that matters; without this it looks filed and simply never answers a question.
 */
const READABILITY: Partial<Record<ExtractionStatus, { tone: string; live?: boolean; label: string; why: string }>> = {
  PENDING: {
    tone: "amber", live: true, label: "Indexing…",
    why: "Being read so the assistant can answer questions from it.",
  },
  NEEDS_OCR: {
    tone: "amber", label: "Scan — not searchable",
    why: "This PDF is images of pages with no text in it, so the assistant can't read it. " +
         "Upload a PDF exported from the original file, or run OCR over this one first.",
  },
  FAILED: {
    tone: "rose", label: "Couldn't be read",
    why: "Something went wrong reading this file, so the assistant can't use it.",
  },
  SKIPPED: {
    tone: "slate", label: "Not searchable",
    why: "This kind of file has no text to read — it's filed here, but the assistant can't " +
         "answer questions from it.",
  },
};

/**
 * One filed document: open it, or remove it.
 *
 * Removing is the fix for filing the wrong thing, which is easy to do and was previously
 * permanent. It asks first, because the file is gone for everyone afterwards — and the
 * chatbot stops quoting it at the same moment, since the text it indexed goes with it.
 */
export function DocumentRow({
  doc,
  onDeleted,
  onError,
}: {
  doc: DocRow;
  onDeleted: () => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const readability = READABILITY[doc.extraction_status];

  async function remove() {
    const confirmed = window.confirm(
      `Delete “${doc.title}”?\n\nThe file is removed for everyone and the assistant stops ` +
      `using it. This can't be undone.`,
    );
    if (!confirmed) return;

    setBusy(true);
    try {
      await api.del(`/documents/${doc.id}`);
      onDeleted();
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "Could not delete that file.");
      setBusy(false);        // stays mounted on failure; on success the row goes away
    }
  }

  return (
    <li className="group flex items-center justify-between gap-3 px-4 py-2.5">
      <div className="min-w-0">
        <a
          href={`${API}/documents/${doc.id}/download`}
          className="truncate text-sm hover:underline"
          style={{ color: "var(--accent)" }}
        >
          {doc.title}
        </a>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px]"
             style={{ color: "var(--text-subtle)" }}>
          <span>
            {titleCase(doc.kind)}
            {doc.size_bytes ? ` · ${Math.max(1, Math.round(doc.size_bytes / 1024))} KB` : ""}
          </span>
          {readability ? (
            <Badge tone={readability.tone} lamp live={readability.live}
                   title={doc.extraction_error || readability.why}>
              {readability.label}
            </Badge>
          ) : null}
        </div>
      </div>
      <Button
        size="sm"
        variant="ghost"
        loading={busy}
        onClick={() => void remove()}
        title={`Delete ${doc.title}`}
        aria-label={`Delete ${doc.title}`}
        /* Visible on hover and whenever focused, so it is reachable by keyboard but doesn't
           put a row of delete buttons in front of someone reading the folder. */
        className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
        style={{ color: "var(--danger)" }}
      >
        <TrashIcon />
      </Button>
    </li>
  );
}

function TrashIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden
         stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2.5 4.5h11M6.5 4.5V3a1 1 0 0 1 1-1h1a1 1 0 0 1 1 1v1.5" />
      <path d="M4 4.5l.6 8a1 1 0 0 0 1 .9h4.8a1 1 0 0 0 1-.9l.6-8" />
      <path d="M6.75 7v3.75M9.25 7v3.75" />
    </svg>
  );
}
