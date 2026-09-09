"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { useAsync, useDebounced } from "@/lib/hooks";
import { useRequireSession } from "@/lib/session";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Alert, Button, Card, CardHeader, EmptyState, Field, Input, Select, StatusBadge, Table, Td, Textarea, Th } from "@/components/ui";
import { formatDate, money, titleCase } from "@/lib/format";
import type { DealDetail, DealRow } from "@/lib/types";

const STATUSES = [
  "LEAD", "NEGOTIATING", "AGREED", "IN_PROGRESS", "SHIPPED", "COMPLETED", "ON_HOLD", "LOST",
];

export default function DealsPage() {
  const { user, loading } = useRequireSession();
  const [search, setSearch] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [openOnly, setOpenOnly] = React.useState(false);
  const [creating, setCreating] = React.useState(false);
  const debounced = useDebounced(search);

  const deals = useAsync(
    () => api.get<DealRow[]>("/deals", {
      search: debounced || undefined,
      deal_status: status || undefined,
      open_only: openOnly || undefined,
    }),
    [debounced, status, openOnly],
  );

  if (loading || !user) return null;

  return (
    <AppShell>
      <PageHeader
        title="Deals"
        subtitle={deals.data ? `${deals.data.length} deal${deals.data.length === 1 ? "" : "s"}` : "Loading…"}
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            New deal
          </Button>
        }
      />

      {creating ? <NewDeal onClose={() => setCreating(false)} /> : null}

      <Card rail>
        <CardHeader
          title="All deals"
          actions={
            <div className="flex flex-wrap gap-2">
              <Input
                placeholder="Search title or number"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-56"
              />
              <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-44">
                <option value="">Any status</option>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>{titleCase(s)}</option>
                ))}
              </Select>
              <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
                <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
                Open only
              </label>
            </div>
          }
        />
        {deals.error ? (
          <div className="p-4"><Alert>{deals.error}</Alert></div>
        ) : deals.loading ? (
          <EmptyState title="Loading…" />
        ) : (deals.data?.length ?? 0) === 0 ? (
          <EmptyState title="No deals match" hint="Try clearing the filters, or start a new deal." />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Deal</Th><Th>Chain</Th><Th>Status</Th>
                <Th align="right">Value</Th><Th align="right">Our commission</Th><Th>Ships</Th>
              </tr>
            </thead>
            <tbody>
              {deals.data?.map((d) => (
                <tr key={d.id}>
                  <Td>
                    <Link href={`/deals/${d.id}`} className="font-medium hover:underline">
                      {d.title}
                    </Link>
                    <div className="font-mono text-[11px]" style={{ color: "var(--text-subtle)" }}>
                      {d.deal_no}
                    </div>
                  </Td>
                  <Td>
                    <div className="flex flex-wrap items-center gap-1 text-xs">
                      {d.counterparties.map((name, i) => (
                        <React.Fragment key={`${name}-${i}`}>
                          {i > 0 ? <span style={{ color: "var(--text-subtle)" }}>→</span> : null}
                          <span>{name}</span>
                        </React.Fragment>
                      ))}
                    </div>
                  </Td>
                  <Td><StatusBadge status={d.status} /></Td>
                  <Td align="right">{money(d.value)}</Td>
                  <Td align="right" className="font-medium">{money(d.commission)}</Td>
                  <Td>{formatDate(d.target_ship_date)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </AppShell>
  );
}

function NewDeal({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [form, setForm] = React.useState({ title: "", description: "", target_ship_date: "" });
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  return (
    <Card className="mb-5">
      <CardHeader title="New deal" subtitle="Add the parties and their commission once it exists" />
      <form
        className="space-y-3 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          void (async () => {
            try {
              const deal = await api.post<DealDetail>("/deals", {
                title: form.title,
                description: form.description || undefined,
                target_ship_date: form.target_ship_date || undefined,
              });
              router.push(`/deals/${deal.id}`);
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "Could not create that deal.");
              setBusy(false);
            }
          })();
        }}
      >
        <Field label="What is the deal?" required>
          <Input
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Australian cotton — 240 MT to Sri Vaari"
            required
          />
        </Field>
        <Field label="Description">
          <Textarea
            rows={2}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Who supplies what to whom, and how we earn on it."
          />
        </Field>
        <Field label="Target ship date">
          <Input
            type="date"
            value={form.target_ship_date}
            onChange={(e) => setForm({ ...form, target_ship_date: e.target.value })}
            className="w-48"
          />
        </Field>
        {error ? <Alert>{error}</Alert> : null}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" loading={busy} disabled={form.title.length < 3}>
            Create
          </Button>
          <Button type="button" onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
