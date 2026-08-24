"use client";

import * as React from "react";

import { ApiError, api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { PageHeader } from "@/components/AppShell";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Table,
  Td,
  Textarea,
  Th,
} from "@/components/ui";
import { formatCell, formatDate, statusTone, titleCase } from "@/lib/format";
import type { ChangePreview, Page } from "@/lib/types";

/**
 * Natural-language record editing.
 *
 * Describe the change; it runs inside a transaction, the real before/after rows come back, and
 * the transaction is rolled back. What you see below is not a prediction of what would happen —
 * it is what did happen, in a transaction that was then discarded. Confirming re-runs it for
 * real, after checking those rows have not changed underneath you.
 */
export default function DataEditor() {
  const [prompt, setPrompt] = React.useState("");
  const [sql, setSql] = React.useState("");
  const [showSql, setShowSql] = React.useState(false);
  const [preview, setPreview] = React.useState<ChangePreview | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [question, setQuestion] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [applied, setApplied] = React.useState<string | null>(null);

  const history = useAsync(() => api.get<Page<ChangePreview>>("/nlsql", { page_size: 15 }), [applied]);

  async function propose(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setQuestion(null);
    setPreview(null);
    setApplied(null);
    try {
      const result = await api.post<ChangePreview>("/nlsql/propose", {
        prompt,
        sql: showSql && sql.trim() ? sql.trim() : undefined,
      });
      setPreview(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        // The planner declined to guess. That is the desired behaviour for a tool that edits
        // records — surface the question rather than an error.
        setQuestion(err.message);
      } else if (err instanceof ApiError && err.status === 503) {
        setError(`${err.message} You can still paste SQL directly using "Write the SQL myself".`);
      } else {
        setError(err instanceof ApiError ? err.message : "Could not prepare that change.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/nlsql/${preview.id}/confirm`);
      setApplied(`Applied to ${preview.affected_count} row${preview.affected_count === 1 ? "" : "s"}.`);
      setPreview(null);
      setPrompt("");
      setSql("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not apply that change.");
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    if (!preview) return;
    await api.post(`/nlsql/${preview.id}/discard`);
    setPreview(null);
  }

  return (
    <>
      <PageHeader
        title="Data editor"
        subtitle="Describe a correction in plain English. Nothing is saved until you confirm the diff."
        actions={<Badge tone="amber">Super Admin only</Badge>}
      />

      <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
        <div className="space-y-5">
          <Card>
            <CardHeader title="What needs changing?" />
            <form onSubmit={propose} className="space-y-3 p-5">
              <Textarea
                rows={3}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Kovai Knits' minimum order for circular knitting is 1000 pieces, not 5000"
                required
              />

              <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
                <input
                  type="checkbox"
                  checked={showSql}
                  onChange={(e) => setShowSql(e.target.checked)}
                />
                Write the SQL myself
              </label>

              {showSql ? (
                <Field
                  label="SQL"
                  hint="One INSERT, UPDATE or DELETE. The same guard and preview apply either way."
                >
                  <Textarea
                    rows={3}
                    value={sql}
                    onChange={(e) => setSql(e.target.value)}
                    className="font-mono text-xs"
                    placeholder="UPDATE supplier_process SET min_order_qty = 1000 WHERE id = '…'"
                  />
                </Field>
              ) : null}

              <Button type="submit" variant="primary" loading={busy} disabled={!prompt.trim()}>
                Preview the change
              </Button>

              {error ? <Alert>{error}</Alert> : null}
              {question ? (
                <Alert tone="amber">
                  <strong className="font-medium">One question first: </strong>
                  {question}
                </Alert>
              ) : null}
              {applied ? <Alert tone="emerald">{applied}</Alert> : null}
            </form>
          </Card>

          {preview ? <PreviewPanel preview={preview} onConfirm={confirm} onDiscard={discard} busy={busy} /> : null}
        </div>

        <Card>
          <CardHeader title="Recent changes" subtitle="Applied, discarded and refused alike" />
          {(history.data?.items.length ?? 0) === 0 ? (
            <EmptyState title="No changes yet" />
          ) : (
            <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
              {history.data?.items.map((change) => (
                <li key={change.id} className="px-4 py-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="min-w-0 flex-1 text-xs">{change.prompt}</p>
                    <Badge tone={statusTone(change.status)}>{titleCase(change.status)}</Badge>
                  </div>
                  <div className="mt-1 text-[11px]" style={{ color: "var(--text-subtle)" }}>
                    {change.statement_kind} on {change.target_table} · {change.affected_count} row
                    {change.affected_count === 1 ? "" : "s"} · {formatDate(change.created_at)}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

function PreviewPanel({
  preview,
  onConfirm,
  onDiscard,
  busy,
}: {
  preview: ChangePreview;
  onConfirm: () => void;
  onDiscard: () => void;
  busy: boolean;
}) {
  const rows = preview.diff ?? [];

  return (
    <Card>
      <CardHeader
        title={`${preview.affected_count} row${preview.affected_count === 1 ? "" : "s"} would change`}
        subtitle={
          preview.explanation ??
          `${preview.statement_kind} on ${preview.target_table}. Run in a transaction and rolled back — nothing is saved yet.`
        }
        actions={
          <>
            <Button size="sm" onClick={onDiscard}>
              Discard
            </Button>
            <Button size="sm" variant="primary" loading={busy} onClick={onConfirm}>
              Confirm and apply
            </Button>
          </>
        }
      />

      <div className="border-b px-5 py-3" style={{ borderColor: "var(--border)" }}>
        <code className="block text-[11px] leading-relaxed break-all" style={{ color: "var(--text-muted)" }}>
          {preview.generated_sql}
        </code>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          title="Nothing matched"
          hint="The statement is valid but no rows meet its condition. Nothing would change."
        />
      ) : (
        <div className="divide-y" style={{ borderColor: "var(--border)" }}>
          {rows.map((row, index) => (
            <div key={`${row.pk.join("-")}-${index}`} className="px-5 py-4">
              <div className="mb-2 flex items-center gap-2">
                <Badge
                  tone={
                    row.operation === "DELETE" ? "rose" : row.operation === "INSERT" ? "emerald" : "sky"
                  }
                >
                  {row.operation}
                </Badge>
                <code className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                  {row.pk.join(", ")}
                </code>
              </div>

              {row.operation === "UPDATE" ? (
                <Table>
                  <thead>
                    <tr>
                      <Th>Column</Th>
                      <Th>Before</Th>
                      <Th>After</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(row.changes).map(([column, cell]) => (
                      <tr key={column}>
                        <Td className="font-medium">{column}</Td>
                        <Td>
                          <span
                            className="rounded px-1.5 py-0.5 font-mono text-xs line-through"
                            style={{ background: "var(--danger-soft)", color: "var(--danger)" }}
                          >
                            {formatCell(cell.before)}
                          </span>
                        </Td>
                        <Td>
                          <span
                            className="rounded px-1.5 py-0.5 font-mono text-xs"
                            style={{ background: "var(--success-soft)", color: "var(--success)" }}
                          >
                            {formatCell(cell.after)}
                          </span>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              ) : (
                <RowSnapshot
                  values={(row.operation === "DELETE" ? row.before : row.after) ?? {}}
                  tone={row.operation === "DELETE" ? "danger" : "success"}
                />
              )}
            </div>
          ))}
        </div>
      )}

      <div
        className="flex items-center gap-2 border-t px-5 py-3 text-xs"
        style={{ borderColor: "var(--border)", color: "var(--text-subtle)" }}
      >
        Confirming re-checks that these rows have not changed since this preview. If someone
        else edited them in the meantime, it is refused rather than applied over their work.
      </div>
    </Card>
  );
}

function RowSnapshot({
  values,
  tone,
}: {
  values: Record<string, unknown>;
  tone: "danger" | "success";
}) {
  const entries = Object.entries(values).filter(
    ([key]) => !["created_at", "updated_at"].includes(key),
  );
  return (
    <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="flex justify-between gap-3 text-xs">
          <dt style={{ color: "var(--text-subtle)" }}>{key}</dt>
          <dd
            className="truncate rounded px-1.5 font-mono"
            style={{
              background: tone === "danger" ? "var(--danger-soft)" : "var(--success-soft)",
              color: tone === "danger" ? "var(--danger)" : "var(--success)",
            }}
            title={formatCell(value)}
          >
            {formatCell(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
