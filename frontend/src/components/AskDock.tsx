"use client";

import * as React from "react";
import { usePathname } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import {
  Alert, Badge, Button, Table, Td, Th, Textarea,
} from "@/components/ui";
import { formatCell, titleCase } from "@/lib/format";
import type { AskResponse, ChatHealth } from "@/lib/types";

interface Turn {
  question: string;
  response: AskResponse | null;
  error: string | null;
}

const CATEGORY_TONE: Record<string, string> = {
  DATABASE: "sky", TECHNICAL: "emerald", CREATIVE: "amber",
};

/**
 * A composer docked to the bottom of every screen, which opens into a thread when you use it.
 *
 * It is not a page for two reasons. Asking is something you do *while* looking at a deal, not
 * a place you navigate to — and once it is always present, the answer can be about what is on
 * screen. The page context travels with the question so "what's outstanding on this one" works
 * without naming the deal.
 */
export function AskDock() {
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);
  const [question, setQuestion] = React.useState("");
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [busy, setBusy] = React.useState(false);
  const health = useAsync(() => api.get<ChatHealth>("/chat/health"), []);
  const endRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length, busy, open]);

  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && open) setOpen(false);
      // ⌘K from anywhere, the way every other command box works.
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen(true);
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  async function ask() {
    const q = question.trim();
    if (!q || busy) return;

    setQuestion("");
    setOpen(true);
    setBusy(true);
    setTurns((t) => [...t, { question: q, response: null, error: null }]);
    try {
      const response = await api.post<AskResponse>("/chat/ask", {
        question: q,
        context: pageContext(pathname),
      });
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, response } : turn)));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Something went wrong.";
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, error: message } : turn)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 flex justify-center px-4 pb-4">
      <div className="pointer-events-auto w-full max-w-3xl">
        {open && (turns.length > 0 || busy) ? (
          <div
            className="mb-2 overflow-hidden rounded-xl border shadow-lg"
            style={{ background: "var(--surface)", borderColor: "var(--border-strong)" }}
          >
            <div
              className="flex items-center justify-between gap-3 border-b px-4 py-2"
              style={{ borderColor: "var(--border)" }}
            >
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold">Ask</span>
                {health.data?.is_stub ? (
                  <Badge tone="amber" title="Keyword routing and templated answers — not a model.">
                    Stub backend
                  </Badge>
                ) : null}
              </div>
              <div className="flex items-center gap-1">
                {turns.length ? (
                  <Button size="sm" variant="ghost" onClick={() => setTurns([])}>Clear</Button>
                ) : null}
                <Button size="sm" variant="ghost" onClick={() => setOpen(false)} aria-label="Close">
                  ✕
                </Button>
              </div>
            </div>

            <div className="max-h-[58vh] space-y-3 overflow-y-auto px-4 py-3">
              {turns.map((turn, i) => <TurnBlock key={i} turn={turn} />)}
              {busy ? (
                <p className="text-sm" style={{ color: "var(--text-muted)" }}>Thinking…</p>
              ) : null}
              <div ref={endRef} />
            </div>
          </div>
        ) : null}

        <div
          className="flex items-end gap-2 rounded-xl border p-2 shadow-lg"
          style={{ background: "var(--surface)", borderColor: "var(--border-strong)" }}
        >
          <Textarea
            ref={inputRef}
            rows={1}
            value={question}
            onFocus={() => setOpen(true)}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends; shift-enter is a newline. The usual contract.
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void ask();
              }
            }}
            placeholder={placeholderFor(pathname)}
            className="max-h-32 min-h-[38px] resize-none border-0 shadow-none focus:outline-none"
            style={{ background: "transparent" }}
          />
          <Button
            variant="primary"
            size="sm"
            loading={busy}
            disabled={!question.trim()}
            onClick={() => void ask()}
          >
            Ask
          </Button>
        </div>
      </div>
    </div>
  );
}

/** What the user is looking at, so a follow-up need not name it. */
function pageContext(pathname: string): string | undefined {
  const deal = pathname.match(/^\/deals\/([0-9a-f-]{36})/i);
  if (deal) return `The user is currently viewing deal ${deal[1]}.`;
  const company = pathname.match(/^\/companies\/([0-9a-f-]{36})/i);
  if (company) return `The user is currently viewing company ${company[1]}.`;
  if (pathname === "/deals") return "The user is looking at the list of deals.";
  if (pathname === "/companies") return "The user is looking at the list of companies.";
  if (pathname === "/") return "The user is looking at the dashboard.";
  return undefined;
}

function placeholderFor(pathname: string): string {
  if (/^\/deals\/[0-9a-f-]{36}/i.test(pathname)) return "Ask about this deal…";
  if (/^\/companies\/[0-9a-f-]{36}/i.test(pathname)) return "Ask about this company…";
  return "Ask about deals, companies or documents…    ⌘K";
}

function TurnBlock({ turn }: { turn: Turn }) {
  const r = turn.response;
  return (
    <div className="space-y-1.5">
      <div className="flex justify-end">
        <div
          className="max-w-[85%] rounded-lg px-3 py-1.5 text-sm"
          style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
        >
          {turn.question}
        </div>
      </div>

      {turn.error ? <Alert>{turn.error}</Alert> : null}

      {r ? (
        <div
          className="rounded-lg border"
          style={{ background: "var(--surface-2)", borderColor: "var(--border)" }}
        >
          <div className="flex flex-wrap items-center gap-2 px-3 pt-2">
            {r.needs_clarification ? (
              <Badge tone="amber">Needs clarification</Badge>
            ) : r.category ? (
              <Badge tone={CATEGORY_TONE[r.category] ?? "slate"}>{titleCase(r.category)}</Badge>
            ) : null}
            {r.secondary ? (
              <Badge tone={CATEGORY_TONE[r.secondary] ?? "slate"}>+ {titleCase(r.secondary)}</Badge>
            ) : null}
            {r.confidence !== null ? (
              <span className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                {Math.round(r.confidence * 100)}% confident
              </span>
            ) : null}
          </div>

          <p className="px-3 py-2 text-sm whitespace-pre-wrap">{r.answer}</p>

          {r.citations.length ? (
            <div className="flex flex-wrap gap-1 px-3 pb-2">
              {r.citations.map((c) => <Badge key={c}>{c}</Badge>)}
            </div>
          ) : null}

          {r.sql ? (
            <code
              className="block border-t px-3 py-1.5 text-[11px] break-all"
              style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
            >
              {r.sql}
            </code>
          ) : null}

          {r.rows?.length ? (
            <div className="border-t" style={{ borderColor: "var(--border)" }}>
              <Table>
                <thead>
                  <tr>{Object.keys(r.rows[0]).map((c) => <Th key={c}>{c}</Th>)}</tr>
                </thead>
                <tbody>
                  {r.rows.slice(0, 8).map((row, i) => (
                    <tr key={i}>
                      {Object.keys(r.rows![0]).map((c) => <Td key={c}>{formatCell(row[c])}</Td>)}
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          ) : null}

          {r.pending_write && r.pending_write_id ? (
            <WritePreview id={r.pending_write_id} write={r.pending_write} />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function WritePreview({
  id, write,
}: { id: string; write: NonNullable<AskResponse["pending_write"]> }) {
  const [state, setState] = React.useState<"pending" | "applied" | "discarded">("pending");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  return (
    <div className="border-t px-3 py-2" style={{ borderColor: "var(--border)" }}>
      <div className="mb-2 flex items-center gap-2">
        <Badge tone="amber">{write.kind}</Badge>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          {write.affected} row(s) in {write.table} — nothing saved yet
        </span>
      </div>

      {write.diff.slice(0, 4).map((row, i) => (
        <Table key={i}>
          <thead><tr><Th>Column</Th><Th>Before</Th><Th>After</Th></tr></thead>
          <tbody>
            {Object.entries(row.changes).map(([col, cell]) => (
              <tr key={col}>
                <Td className="font-medium">{col}</Td>
                <Td>
                  <span className="rounded px-1.5 font-mono text-xs line-through"
                        style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
                    {formatCell(cell.before)}
                  </span>
                </Td>
                <Td>
                  <span className="rounded px-1.5 font-mono text-xs"
                        style={{ background: "var(--success-soft)", color: "var(--success)" }}>
                    {formatCell(cell.after)}
                  </span>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      ))}

      {error ? <Alert>{error}</Alert> : null}

      {state === "pending" ? (
        <div className="mt-2 flex gap-2">
          <Button
            size="sm" variant="primary" loading={busy}
            onClick={async () => {
              setBusy(true); setError(null);
              try {
                await api.post(`/chat/confirm/${id}`);
                setState("applied");
              } catch (err) {
                setError(err instanceof ApiError ? err.message : "Could not apply.");
              } finally { setBusy(false); }
            }}
          >
            Confirm and apply
          </Button>
          <Button size="sm" onClick={async () => {
            await api.post(`/chat/discard/${id}`); setState("discarded");
          }}>
            Discard
          </Button>
        </div>
      ) : (
        <Alert tone={state === "applied" ? "emerald" : "sky"}>
          {state === "applied" ? "Applied." : "Discarded — nothing was changed."}
        </Alert>
      )}
    </div>
  );
}
