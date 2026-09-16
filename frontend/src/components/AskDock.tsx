"use client";

import * as React from "react";
import { usePathname } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { useConversation, type Turn, type WriteState } from "@/lib/conversation";
import { Alert, Badge, Button, Lamp, Textarea } from "@/components/ui";
import { formatCell } from "@/lib/format";
import type { AskResponse, ChatHealth } from "@/lib/types";

/**
 * A composer docked to the bottom of every screen, which opens into a conversation.
 *
 * It is not a page for two reasons. Asking is something you do *while* looking at a deal, not a
 * place you navigate to — and once it is always present, the answer can be about what is on
 * screen. The page context travels with the question so "what's outstanding on this one" works
 * without naming the deal; it is never shown as a label, because a chip on every question was
 * noise once the conversation reads the same on every page.
 *
 * The thread itself lives in ConversationProvider, above the pages — see lib/conversation.tsx.
 */
export function AskDock() {
  const pathname = usePathname();
  const { turns, busy, open, setOpen, ask, clear } = useConversation();
  const [question, setQuestion] = React.useState("");
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
  }, [open, setOpen]);

  function send() {
    const q = question.trim();
    if (!q || busy) return;
    setQuestion("");
    setOpen(true);
    void ask(q, pageContext(pathname));
  }

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 flex justify-center px-4 pb-4">
      <div className="pointer-events-auto w-full max-w-3xl">
        {open && (turns.length > 0 || busy) ? (
          <div
            className="mb-2 overflow-hidden border shadow-lg"
            style={{
              background: "var(--surface)",
              borderColor: "var(--border-strong)",
              borderRadius: 3,
            }}
          >
            <div
              className="flex items-center justify-between gap-3 border-b px-4 py-2"
              style={{ borderColor: "var(--border)" }}
            >
              <div className="flex items-center gap-2">
                <span className="micro">Ask</span>
                {health.data?.is_stub ? (
                  <Badge tone="amber" title="Keyword routing and templated answers — not a model.">
                    Stub backend
                  </Badge>
                ) : null}
              </div>
              <div className="flex items-center gap-1">
                {turns.length ? (
                  <Button size="sm" variant="ghost" onClick={clear}>Clear</Button>
                ) : null}
                <Button size="sm" variant="ghost" onClick={() => setOpen(false)} aria-label="Close">
                  ✕
                </Button>
              </div>
            </div>

            <div className="max-h-[58vh] overflow-y-auto px-4 py-4">
              <div className="flex flex-col gap-5">
                {turns.map((turn) => <TurnBlock key={turn.id} turn={turn} />)}
                {busy ? <Working /> : null}
              </div>
              <div ref={endRef} />
            </div>
          </div>
        ) : null}

        <div
          className="flex items-end gap-2 border p-2 shadow-lg"
          style={{
            background: "var(--surface)",
            borderColor: "var(--border-strong)",
            borderRadius: 3,
          }}
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
                send();
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
            onClick={send}
          >
            Ask
          </Button>
        </div>
      </div>
    </div>
  );
}

/** What the user is looking at, so a follow-up need not name it. Sent, never displayed. */
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

/** The only visible trace of page context: what the empty box invites you to ask. */
function placeholderFor(pathname: string): string {
  if (/^\/deals\/[0-9a-f-]{36}/i.test(pathname)) return "Ask about this deal…";
  if (/^\/companies\/[0-9a-f-]{36}/i.test(pathname)) return "Ask about this company…";
  return "Ask about deals, companies or documents…    ⌘K";
}

/**
 * How long the question has been running, and nothing more.
 *
 * The backend answers in one POST — there is no stream to report stages from, so naming steps
 * here would be inventing progress. The elapsed second is true, and after ten of them the note
 * explains the wait, because a cold local model spends half a minute loading before it thinks.
 */
function Working() {
  const [seconds, setSeconds] = React.useState(0);

  React.useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(
      () => setSeconds(Math.round((Date.now() - started) / 1000)),
      500,
    );
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-muted)" }}>
      <Lamp tone="sky" live />
      <span>Working</span>
      <span className="readout text-xs">{seconds}s</span>
      {seconds >= 10 ? (
        <span className="text-xs">· the model may still be loading</span>
      ) : null}
    </div>
  );
}

function TurnBlock({ turn }: { turn: Turn }) {
  const r = turn.response;
  return (
    <div className="flex flex-col gap-3">
      {/* The only soft shape in the interface is the thing a person typed. */}
      <div className="flex justify-end">
        <div
          className="max-w-[85%] px-3.5 py-2 text-sm"
          style={{
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: "14px 14px 3px 14px",
          }}
        >
          {turn.question}
        </div>
      </div>

      {turn.error ? <Alert>{turn.error}</Alert> : null}

      {r ? <Answer turn={turn} response={r} /> : null}
    </div>
  );
}

/**
 * An answer is prose on the page, not a bubble.
 *
 * Bubbles are for turn-taking between two people. Here one side is reporting deal figures, and
 * a column of grey capsules makes a long answer harder to read than plain text does.
 */
function Answer({ turn, response }: { turn: Turn; response: AskResponse }) {
  const rows = response.rows ?? [];
  return (
    <div className="flex flex-col gap-3">
      {response.needs_clarification ? <span className="micro">Needs clarification</span> : null}

      <p className="prose-measure text-sm leading-relaxed whitespace-pre-wrap">
        <WithCitations text={response.answer} citations={response.citations} />
      </p>

      {rows.length === 1 ? <RecordStrip row={rows[0]} /> : null}
      {rows.length > 1 ? <RowsTable rows={rows} /> : null}

      {response.citations.length ? <Sources citations={response.citations} /> : null}

      {response.sql ? <QueryLine sql={response.sql} /> : null}

      {response.pending_write && response.pending_write_id ? (
        <WritePanel
          turnId={turn.id}
          id={response.pending_write_id}
          write={response.pending_write}
          state={turn.write_state}
        />
      ) : null}
    </div>
  );
}

/**
 * Citation markers, in the sentence they support.
 *
 * The technical branch already writes "[1]" into its prose; until now those markers sat in the
 * text as literal brackets while the sources piled up underneath, with no way to tell which
 * claim each one backed.
 */
function WithCitations({ text, citations }: { text: string; citations: string[] }) {
  if (!citations.length) return <>{text}</>;

  const parts = text.split(/(\[\d+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[(\d+)\]$/);
        const n = match ? Number(match[1]) : null;
        if (!n || n > citations.length) return <React.Fragment key={i}>{part}</React.Fragment>;
        return (
          <sup
            key={i}
            title={citations[n - 1]}
            className="readout mx-0.5 px-1 text-[11px]"
            style={{
              background: "var(--accent-soft)",
              color: "var(--accent)",
              borderRadius: 2,
              verticalAlign: "baseline",
            }}
          >
            {n}
          </sup>
        );
      })}
    </>
  );
}

/** The documents an answer stood on, named once and quietly. */
function Sources({ citations }: { citations: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className="micro">Read</span>
      {citations.map((c, i) => (
        <span key={c} className="text-xs" style={{ color: "var(--text-muted)" }}>
          <span className="readout" style={{ color: "var(--accent)" }}>{i + 1}</span>{" "}
          {c}
        </span>
      ))}
    </div>
  );
}

// Columns that name the thing a row is about, best first. Whichever appears becomes the strip's
// heading instead of sitting in the grid as another anonymous field.
const NAME_COLUMNS = ["deal_no", "title", "name", "company", "company_name", "deal", "email"];
const ID_COLUMN = /(^|_)id$/;

/**
 * One row, read as a record rather than a table with a single line in it.
 *
 * A lookup that returns one deal is the commonest answer in the app, and a one-row table makes
 * you read the header to learn what each cell is. Labelled fields do not.
 */
function RecordStrip({ row }: { row: Record<string, unknown> }) {
  const keys = Object.keys(row).filter((k) => !ID_COLUMN.test(k));
  const nameKey = NAME_COLUMNS.find((c) => keys.includes(c));
  const fields = keys.filter((k) => k !== nameKey).slice(0, 6);

  return (
    <div
      className="border"
      style={{ background: "var(--surface-2)", borderColor: "var(--border)", borderRadius: 3 }}
    >
      {nameKey ? (
        <div className="border-b px-4 py-2.5" style={{ borderColor: "var(--border)" }}>
          <div className="display text-sm font-semibold">{formatCell(row[nameKey])}</div>
        </div>
      ) : null}
      <div className="grid gap-x-5 gap-y-3 px-4 py-3"
           style={{ gridTemplateColumns: "repeat(auto-fit, minmax(118px, 1fr))" }}>
        {fields.map((key) => (
          <div key={key} className="flex flex-col gap-0.5">
            <span className="micro">{key.replace(/_/g, " ")}</span>
            <span className="readout text-sm">{formatCell(row[key])}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Several rows still need a table — but a quiet one, capped, and honest about what it hides. */
function RowsTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  const columns = Object.keys(rows[0]).filter((k) => !ID_COLUMN.test(k)).slice(0, 5);
  const shown = rows.slice(0, 8);

  return (
    <div
      className="overflow-x-auto border"
      style={{ background: "var(--surface-2)", borderColor: "var(--border)", borderRadius: 3 }}
    >
      <table className="w-full text-sm">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} className="micro border-b px-4 py-2 text-left"
                  style={{ borderColor: "var(--border)" }}>
                {c.replace(/_/g, " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c} className="readout border-t px-4 py-2 text-[13px]"
                    style={{ borderColor: "var(--border)" }}>
                  {formatCell(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length ? (
        <div className="border-t px-4 py-2 text-xs"
             style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}>
          {rows.length - shown.length} more row{rows.length - shown.length === 1 ? "" : "s"} not shown
        </div>
      ) : null}
    </div>
  );
}

/** The query that produced the numbers, folded away until someone doubts them. */
function QueryLine({ sql }: { sql: string }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div>
      <button
        type="button"
        className="micro"
        style={{ color: "var(--accent)" }}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Hide the query" : "Show the query"}
      </button>
      {open ? (
        <code
          className="readout mt-1.5 block border px-3 py-2 text-[11px] break-all"
          style={{
            borderColor: "var(--border)",
            background: "var(--surface-2)",
            color: "var(--text-muted)",
            borderRadius: 3,
          }}
        >
          {sql}
        </code>
      ) : null}
    </div>
  );
}

/**
 * A change to real deal data, waiting for a person.
 *
 * The only panel in the interface with a strong edge and a live lamp, because it is the only one
 * that is about to alter the database. It mirrors what the backend already does: the statement
 * has been run inside a transaction and rolled back, so what is shown is a real before and
 * after, and nothing is committed until the button is pressed.
 */
function WritePanel({
  turnId, id, write, state,
}: {
  turnId: string;
  id: string;
  write: NonNullable<AskResponse["pending_write"]>;
  state: WriteState;
}) {
  const { setWriteState } = useConversation();
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  return (
    <div
      className="border"
      style={{ background: "var(--surface)", borderColor: "var(--border-strong)", borderRadius: 3 }}
    >
      <div
        className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5"
        style={{ borderColor: "var(--border)" }}
      >
        <span className="flex items-center gap-2 text-xs font-semibold"
              style={{ color: state === "pending" ? "var(--warning)" : "var(--text-muted)" }}>
          <Lamp tone={state === "pending" ? "amber" : "slate"} live={state === "pending"} />
          {state === "pending" ? "Waiting for you · nothing saved"
            : state === "applied" ? "Saved"
            : "Discarded · nothing changed"}
        </span>
        <span className="micro">
          {write.affected} row{write.affected === 1 ? "" : "s"} · {write.table}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              {["Field", "Now", "After"].map((h) => (
                <th key={h} className="micro px-4 pt-3 pb-1.5 text-left">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {write.diff.slice(0, 4).flatMap((row, i) =>
              Object.entries(row.changes).map(([column, cell]) => (
                <tr key={`${i}-${column}`}>
                  <td className="border-t px-4 py-2" style={{ borderColor: "var(--border)" }}>
                    {column.replace(/_/g, " ")}
                  </td>
                  <td className="readout border-t px-4 py-2 text-[13px] line-through"
                      style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}>
                    {formatCell(cell.before)}
                  </td>
                  <td className="border-t px-4 py-2" style={{ borderColor: "var(--border)" }}>
                    <span className="readout px-1.5 py-0.5 text-[13px]"
                          style={{ background: "var(--accent-soft)", borderRadius: 2 }}>
                      {formatCell(cell.after)}
                    </span>
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>

      {error ? <div className="px-4 pb-2"><Alert>{error}</Alert></div> : null}

      {state === "pending" ? (
        <div className="flex flex-wrap items-center gap-2 border-t px-4 py-3"
             style={{ borderColor: "var(--border)" }}>
          <Button
            size="sm" variant="primary" loading={busy}
            onClick={async () => {
              setBusy(true); setError(null);
              try {
                await api.post(`/chat/confirm/${id}`);
                setWriteState(turnId, "applied");
              } catch (err) {
                setError(err instanceof ApiError ? err.message : "Could not save the change.");
              } finally { setBusy(false); }
            }}
          >
            Save this change
          </Button>
          <Button size="sm" onClick={async () => {
            try {
              await api.post(`/chat/discard/${id}`);
            } finally {
              setWriteState(turnId, "discarded");
            }
          }}>
            Discard
          </Button>
        </div>
      ) : null}
    </div>
  );
}
