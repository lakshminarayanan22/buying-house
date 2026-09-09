"use client";

import * as React from "react";

import { ApiError, api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { useRequireSession } from "@/lib/session";
import { AppShell, PageHeader } from "@/components/AppShell";
import {
  Alert, Badge, Button, Card, CardHeader, EmptyState, Table, Td, Textarea, Th,
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

export default function ChatPage() {
  const { user, loading } = useRequireSession();
  const health = useAsync(() => api.get<ChatHealth>("/chat/health"), []);
  const [question, setQuestion] = React.useState("");
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [busy, setBusy] = React.useState(false);
  const endRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length, busy]);

  if (loading || !user) return null;

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;

    setQuestion("");
    setBusy(true);
    setTurns((t) => [...t, { question: q, response: null, error: null }]);
    try {
      const response = await api.post<AskResponse>("/chat/ask", { question: q });
      setTurns((t) => t.map((turn, i) =>
        i === t.length - 1 ? { ...turn, response } : turn));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Something went wrong.";
      setTurns((t) => t.map((turn, i) =>
        i === t.length - 1 ? { ...turn, error: message } : turn));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <PageHeader
        title="Ask"
        subtitle="Questions about the records, the documents, or something to draft."
        actions={
          health.data?.is_stub ? (
            <Badge tone="amber" title="Keyword routing and templated answers — not a model.">
              Stub backend
            </Badge>
          ) : health.data ? (
            <Badge tone="emerald">{health.data.branch_model}</Badge>
          ) : null
        }
      />

      {health.data?.is_stub ? (
        <div className="mb-5">
          <Alert tone="amber">
            <strong className="font-medium">Running on the stub backend.</strong>{" "}
            Routing is keyword-based and answers are templates — the plumbing is real, the
            intelligence is not. Set <code>LLM_BACKEND=claude</code> and{" "}
            <code>ANTHROPIC_API_KEY</code> to turn it on. Embeddings are also stubbed
            (<code>{health.data.embedding_model}</code>), so semantic ranking is noise;
            keyword matching still works.
          </Alert>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_300px]">
        <div className="space-y-4">
          {turns.length === 0 ? (
            <Card>
              <EmptyState
                title="Ask something"
                hint="“How much commission is outstanding?” · “What temperature is the Kaimei finish applied at?” · “Which suppliers can dye and hold GOTS?”"
              />
            </Card>
          ) : (
            turns.map((turn, i) => <TurnCard key={i} turn={turn} />)
          )}
          {busy ? (
            <Card className="px-5 py-4">
              <span className="text-sm" style={{ color: "var(--text-muted)" }}>Thinking…</span>
            </Card>
          ) : null}
          <div ref={endRef} />

          <Card>
            <form onSubmit={ask} className="space-y-3 p-4">
              <Textarea
                rows={2}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask about deals, companies, or anything in the uploaded documents…"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void ask(e as never);
                }}
              />
              <div className="flex items-center justify-between">
                <span className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                  ⌘↵ to send
                </span>
                <Button type="submit" variant="primary" loading={busy} disabled={!question.trim()}>
                  Ask
                </Button>
              </div>
            </form>
          </Card>
        </div>

        <Card>
          <CardHeader title="How it routes" />
          <div className="space-y-3 px-4 py-4 text-xs" style={{ color: "var(--text-muted)" }}>
            <p><Badge tone="sky">Database</Badge> — deals, commission, companies, milestones.
              Answered by a query against the records.</p>
            <p><Badge tone="emerald">Technical</Badge> — anything in an uploaded document.
              Answered only from retrieved passages, with citations, or refused.</p>
            <p><Badge tone="amber">Creative</Badge> — drafting and composing, grounded in the
              same sources.</p>
            <p style={{ color: "var(--text-subtle)" }}>
              When it isn&apos;t sure, it asks rather than guessing. Writes are always previewed
              before anything is saved.
            </p>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}

function TurnCard({ turn }: { turn: Turn }) {
  const r = turn.response;
  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <div
          className="max-w-[80%] rounded-lg px-3.5 py-2 text-sm"
          style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
        >
          {turn.question}
        </div>
      </div>

      {turn.error ? <Alert>{turn.error}</Alert> : null}

      {r ? (
        <Card>
          <div
            className="flex flex-wrap items-center gap-2 border-b px-4 py-2"
            style={{ borderColor: "var(--border)" }}
          >
            {r.needs_clarification ? (
              <Badge tone="amber">Needs clarification</Badge>
            ) : r.category ? (
              <Badge tone={CATEGORY_TONE[r.category] ?? "slate"}>{titleCase(r.category)}</Badge>
            ) : null}
            {r.secondary ? (
              <Badge tone={CATEGORY_TONE[r.secondary] ?? "slate"}>
                + {titleCase(r.secondary)}
              </Badge>
            ) : null}
            {r.confidence !== null ? (
              <span className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                {Math.round(r.confidence * 100)}% confident
              </span>
            ) : null}
            {r.reasoning ? (
              <span className="truncate text-[11px]" style={{ color: "var(--text-subtle)" }}
                    title={r.reasoning}>
                · {r.reasoning}
              </span>
            ) : null}
          </div>

          <p className="px-4 py-3 text-sm whitespace-pre-wrap">{r.answer}</p>

          {r.citations.length ? (
            <div className="border-t px-4 py-2.5" style={{ borderColor: "var(--border)" }}>
              <div className="mb-1 text-[11px] tracking-wide uppercase"
                   style={{ color: "var(--text-subtle)" }}>
                Sources
              </div>
              <div className="flex flex-wrap gap-1">
                {r.citations.map((c) => <Badge key={c}>{c}</Badge>)}
              </div>
            </div>
          ) : null}

          {r.sql ? (
            <div className="border-t px-4 py-2.5" style={{ borderColor: "var(--border)" }}>
              <code className="block text-[11px] break-all" style={{ color: "var(--text-muted)" }}>
                {r.sql}
              </code>
            </div>
          ) : null}

          {r.rows?.length ? <RowTable rows={r.rows} /> : null}
          {r.pending_write && r.pending_write_id ? (
            <WritePreview id={r.pending_write_id} write={r.pending_write} />
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}

function RowTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  const columns = Object.keys(rows[0] ?? {});
  return (
    <div className="border-t" style={{ borderColor: "var(--border)" }}>
      <Table>
        <thead><tr>{columns.map((c) => <Th key={c}>{c}</Th>)}</tr></thead>
        <tbody>
          {rows.slice(0, 20).map((row, i) => (
            <tr key={i}>
              {columns.map((c) => <Td key={c}>{formatCell(row[c])}</Td>)}
            </tr>
          ))}
        </tbody>
      </Table>
      {rows.length > 20 ? (
        <p className="px-4 py-2 text-[11px]" style={{ color: "var(--text-subtle)" }}>
          showing 20 of {rows.length}
        </p>
      ) : null}
    </div>
  );
}

function WritePreview({ id, write }: { id: string; write: NonNullable<AskResponse["pending_write"]> }) {
  const [state, setState] = React.useState<"pending" | "applied" | "discarded">("pending");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  return (
    <div className="border-t" style={{ borderColor: "var(--border)" }}>
      <div className="px-4 py-3">
        <div className="mb-2 flex items-center gap-2">
          <Badge tone="amber">{write.kind}</Badge>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {write.affected} row(s) in {write.table} — nothing saved yet
          </span>
        </div>

        {write.diff.slice(0, 5).map((row, i) => (
          <div key={i} className="mb-2">
            {Object.entries(row.changes).length ? (
              <Table>
                <thead><tr><Th>Column</Th><Th>Before</Th><Th>After</Th></tr></thead>
                <tbody>
                  {Object.entries(row.changes).map(([col, cell]) => (
                    <tr key={col}>
                      <Td className="font-medium">{col}</Td>
                      <Td>
                        <span className="rounded px-1.5 py-0.5 font-mono text-xs line-through"
                              style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
                          {formatCell(cell.before)}
                        </span>
                      </Td>
                      <Td>
                        <span className="rounded px-1.5 py-0.5 font-mono text-xs"
                              style={{ background: "var(--success-soft)", color: "var(--success)" }}>
                          {formatCell(cell.after)}
                        </span>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <code className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                {formatCell(row.after ?? row.before)}
              </code>
            )}
          </div>
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
            <Button
              size="sm"
              onClick={async () => {
                await api.post(`/chat/discard/${id}`);
                setState("discarded");
              }}
            >
              Discard
            </Button>
          </div>
        ) : (
          <Alert tone={state === "applied" ? "emerald" : "sky"}>
            {state === "applied" ? "Applied." : "Discarded — nothing was changed."}
          </Alert>
        )}
      </div>
    </div>
  );
}
