"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ApiError, api, uploadFile } from "@/lib/api";
import { useAsync, useReloadWhileIndexing } from "@/lib/hooks";
import { useRequireSession } from "@/lib/session";
import { AppShell, PageHeader, RoleBadge } from "@/components/AppShell";
import { DocumentRow } from "@/components/DocumentRow";
import { Alert, Button, Card, CardHeader, EmptyState, Field, FileUpload, Input, Select, StatusBadge, Table, Td, Th } from "@/components/ui";
import { formatDate, money, titleCase } from "@/lib/format";
import type { CompanyRow, DealDetail, Ref } from "@/lib/types";

const DEAL_STATUSES = [
  "LEAD", "NEGOTIATING", "AGREED", "IN_PROGRESS", "SHIPPED", "COMPLETED", "ON_HOLD", "LOST",
];
const ROLES = ["BUYER", "SUPPLIER", "PROCESSOR", "INPUT_SUPPLIER", "OTHER"];
const BASES = ["NONE", "PERCENTAGE", "MARGIN", "FIXED"];
const COMMISSION_STATUSES = ["NOT_DUE", "DUE", "INVOICED", "RECEIVED", "WRITTEN_OFF"];
const MILESTONE_STATUSES = ["PENDING", "IN_PROGRESS", "DONE", "BLOCKED", "SKIPPED"];

/** One labelled figure in the strip under a deal's title. */
function Readout({
  label,
  accent = false,
  children,
}: {
  label: string;
  accent?: boolean;
  children: React.ReactNode;
}) {
  return (
    <span className="inline-flex flex-col leading-tight">
      <span className="micro">{label}</span>
      <span
        className="readout text-sm font-medium"
        style={accent ? { color: "var(--accent)" } : undefined}
      >
        {children}
      </span>
    </span>
  );
}

export default function DealPage() {
  const { id } = useParams<{ id: string }>();
  const { user, loading } = useRequireSession();
  const deal = useAsync(() => api.get<DealDetail>(`/deals/${id}`), [id]);
  const companies = useAsync(() => api.get<CompanyRow[]>("/companies"), []);
  const processes = useAsync(() => api.get<Ref[]>("/taxonomy", { domain: "PROCESS" }), []);
  const [banner, setBanner] = React.useState<string | null>(null);
  useReloadWhileIndexing(
    (deal.data?.documents ?? []).map((d) => d.extraction_status), deal.reload);

  if (loading || !user) return null;
  if (deal.error) return <AppShell><Alert>{deal.error}</Alert></AppShell>;
  if (!deal.data) return <AppShell><EmptyState title="Loading…" /></AppShell>;

  const d = deal.data;

  async function setStatus(status: string) {
    const body: Record<string, unknown> = { status };
    if (status === "LOST") {
      const reason = window.prompt("Why was it lost? This is the useful part.");
      if (!reason) return;
      body.lost_reason = reason;
    }
    try {
      await api.patch(`/deals/${id}`, body);
      deal.reload();
    } catch (err) {
      setBanner(err instanceof ApiError ? err.message : "Could not change the status.");
    }
  }

  return (
    <AppShell>
      <PageHeader
        title={d.title}
        subtitle={
          /* The strip along the top of a deal is the one thing everyone reads first,
             so it is laid out as labelled instruments rather than a sentence. */
          <span className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <span className="readout text-xs" style={{ color: "var(--text-subtle)" }}>
              {d.deal_no}
            </span>
            <StatusBadge status={d.status} />
            {d.target_ship_date ? (
              <Readout label="Ships">{formatDate(d.target_ship_date)}</Readout>
            ) : null}
            <Readout label="Value">{money(d.value)}</Readout>
            <Readout label="Our commission" accent>{money(d.commission)}</Readout>
          </span>
        }
        actions={
          <Select
            value={d.status}
            onChange={(e) => void setStatus(e.target.value)}
            className="w-44"
          >
            {DEAL_STATUSES.map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
          </Select>
        }
      />

      {banner ? <div className="mb-4"><Alert>{banner}</Alert></div> : null}
      {d.lost_reason ? (
        <div className="mb-4"><Alert tone="rose">Lost — {d.lost_reason}</Alert></div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <div className="space-y-5">
          <Card rail>
            <CardHeader
              title="The chain"
              subtitle="Each company's role on this deal, and what we earn on their leg"
            />
            {d.parties.length === 0 ? (
              <EmptyState title="No parties yet" hint="Add the supplier and the buyer to start." />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>#</Th><Th>Company</Th><Th>Role</Th><Th align="right">Qty</Th>
                    <Th align="right">Value</Th><Th align="right">Commission</Th><Th>Status</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.parties.map((p) => (
                    <tr key={p.id}>
                      <Td>{p.sequence}</Td>
                      <Td>
                        <Link href={`/companies/${p.company_id}`} className="font-medium hover:underline">
                          {p.company_name}
                        </Link>
                        {p.process_name ? (
                          <div className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                            {p.process_name}
                          </div>
                        ) : null}
                      </Td>
                      <Td><RoleBadge role={p.role} /></Td>
                      <Td align="right">
                        {p.qty === null ? "—" : `${p.qty.toLocaleString()} ${p.uom ?? ""}`}
                      </Td>
                      <Td align="right">{money(p.value)}</Td>
                      <Td align="right">
                        <div className="font-medium">{money(p.commission_amount)}</div>
                        <div className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                          {p.commission_basis === "PERCENTAGE" && p.commission_pct
                            ? `${p.commission_pct}%`
                            : p.commission_basis === "MARGIN" &&
                              p.unit_price !== null && p.resale_unit_price !== null
                              ? `${p.unit_price} → ${p.resale_unit_price}`
                              : titleCase(p.commission_basis)}
                        </div>
                      </Td>
                      <Td>
                        <Select
                          value={p.commission_status}
                          className="px-1.5 py-1 text-xs"
                          onChange={async (e) => {
                            try {
                              await api.patch(`/deals/${id}/parties/${p.id}`, {
                                company_id: p.company_id, role: p.role,
                                commission_status: e.target.value,
                                invoiced_on: e.target.value === "INVOICED" && !p.invoiced_on
                                  ? new Date().toISOString().slice(0, 10) : p.invoiced_on,
                                received_on: e.target.value === "RECEIVED" && !p.received_on
                                  ? new Date().toISOString().slice(0, 10) : p.received_on,
                                commission_amount: p.commission_amount,
                              });
                              deal.reload();
                            } catch (err) {
                              setBanner(err instanceof ApiError ? err.message : "Could not update.");
                            }
                          }}
                        >
                          {COMMISSION_STATUSES.map((s) => (
                            <option key={s} value={s}>{titleCase(s)}</option>
                          ))}
                        </Select>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            <AddParty
              dealId={id}
              companies={companies.data ?? []}
              processes={processes.data ?? []}
              nextSequence={d.parties.length + 1}
              onSaved={() => deal.reload()}
              onError={setBanner}
            />
          </Card>

          <Card>
            <CardHeader title="Follow-ups" subtitle="What has to happen, and by when" />
            {d.milestones.length === 0 ? (
              <EmptyState title="No milestones yet" />
            ) : (
              <Table>
                <thead>
                  <tr><Th>Milestone</Th><Th>Planned</Th><Th>Done</Th><Th>Status</Th></tr>
                </thead>
                <tbody>
                  {d.milestones.map((ms) => (
                    <tr key={ms.id}>
                      <Td className="font-medium">{ms.name}</Td>
                      <Td>
                        <span style={{ color: ms.is_overdue ? "var(--danger)" : undefined }}>
                          {formatDate(ms.planned_date)}
                        </span>
                      </Td>
                      <Td>{formatDate(ms.actual_date)}</Td>
                      <Td>
                        <Select
                          value={ms.status}
                          className="px-1.5 py-1 text-xs"
                          onChange={async (e) => {
                            try {
                              await api.patch(`/deals/${id}/milestones/${ms.id}`, {
                                name: ms.name, status: e.target.value,
                              });
                              deal.reload();
                            } catch (err) {
                              setBanner(err instanceof ApiError ? err.message : "Could not update.");
                            }
                          }}
                        >
                          {MILESTONE_STATUSES.map((s) => (
                            <option key={s} value={s}>{titleCase(s)}</option>
                          ))}
                        </Select>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            <AddMilestone dealId={id} onSaved={() => deal.reload()} onError={setBanner} />
          </Card>
        </div>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Folder" subtitle="POs, invoices and everything else for this deal" />
            {d.documents.length === 0 ? (
              <EmptyState title="Nothing filed yet" />
            ) : (
              <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                {d.documents.map((doc) => (
                  <DocumentRow key={doc.id} doc={doc} onDeleted={() => deal.reload()}
                               onError={setBanner} />
                ))}
              </ul>
            )}
            <Upload dealId={id} onSaved={() => deal.reload()} onError={setBanner} />
          </Card>

          {d.description ? (
            <Card>
              <CardHeader title="What this is" />
              <p className="px-5 py-4 text-sm" style={{ color: "var(--text-muted)" }}>
                {d.description}
              </p>
            </Card>
          ) : null}
        </div>
      </div>
    </AppShell>
  );
}

function AddParty({
  dealId, companies, processes, nextSequence, onSaved, onError,
}: {
  dealId: string; companies: CompanyRow[]; processes: Ref[];
  nextSequence: number; onSaved: () => void; onError: (m: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [f, setF] = React.useState({
    company_id: "", role: "SUPPLIER", process_code: "", qty: "", uom: "KG",
    unit_price: "", resale_unit_price: "", value: "",
    commission_basis: "NONE", commission_pct: "", ship_date: "",
  });

  if (!open) {
    return (
      <div className="border-t px-5 py-3" style={{ borderColor: "var(--border)" }}>
        <Button size="sm" onClick={() => setOpen(true)}>Add a company to the chain</Button>
      </div>
    );
  }

  const num = (v: string) => (v === "" ? undefined : Number(v));

  return (
    <div className="border-t px-5 py-4" style={{ borderColor: "var(--border)" }}>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="sm:col-span-2">
          <Field label="Company" required>
            <Select value={f.company_id} onChange={(e) => setF({ ...f, company_id: e.target.value })}>
              <option value="">Choose…</option>
              {companies.map((c) => (
                <option key={c.id} value={c.id}>{c.name}{c.city ? ` — ${c.city}` : ""}</option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Role on this deal" required>
          <Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
            {ROLES.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
          </Select>
        </Field>
        <Field label="Process">
          <Select value={f.process_code} onChange={(e) => setF({ ...f, process_code: e.target.value })}>
            <option value="">—</option>
            {processes.map((p) => <option key={p.id} value={p.code}>{p.name}</option>)}
          </Select>
        </Field>
        <Field label="Quantity">
          <Input value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value.replace(/[^\d.]/g, "") })} />
        </Field>
        <Field label="Unit">
          <Select value={f.uom} onChange={(e) => setF({ ...f, uom: e.target.value })}>
            {["KG", "MT", "PCS", "MTR", "LTR", "BALE"].map((u) => <option key={u}>{u}</option>)}
          </Select>
        </Field>
        <Field label="Value">
          <Input value={f.value} onChange={(e) => setF({ ...f, value: e.target.value.replace(/[^\d.]/g, "") })} />
        </Field>
        <Field label="How we earn">
          <Select
            value={f.commission_basis}
            onChange={(e) => setF({ ...f, commission_basis: e.target.value })}
          >
            {BASES.map((b) => <option key={b} value={b}>{titleCase(b)}</option>)}
          </Select>
        </Field>
        {f.commission_basis === "PERCENTAGE" ? (
          <Field label="Percentage">
            <Input
              value={f.commission_pct}
              onChange={(e) => setF({ ...f, commission_pct: e.target.value.replace(/[^\d.]/g, "") })}
              placeholder="1.5"
            />
          </Field>
        ) : null}
        {f.commission_basis === "MARGIN" ? (
          <>
            <Field label="We pay (per unit)">
              <Input value={f.unit_price}
                     onChange={(e) => setF({ ...f, unit_price: e.target.value.replace(/[^\d.]/g, "") })} />
            </Field>
            <Field label="We sell at (per unit)">
              <Input value={f.resale_unit_price}
                     onChange={(e) => setF({ ...f, resale_unit_price: e.target.value.replace(/[^\d.]/g, "") })} />
            </Field>
          </>
        ) : null}
        <Field label="Ship date">
          <Input type="date" value={f.ship_date} onChange={(e) => setF({ ...f, ship_date: e.target.value })} />
        </Field>
      </div>

      <div className="mt-3 flex gap-2">
        <Button
          size="sm"
          variant="primary"
          loading={busy}
          disabled={!f.company_id}
          onClick={async () => {
            setBusy(true);
            try {
              await api.post(`/deals/${dealId}/parties`, {
                company_id: f.company_id, role: f.role, sequence: nextSequence,
                process_code: f.process_code || undefined,
                qty: num(f.qty), uom: f.uom, value: num(f.value),
                unit_price: num(f.unit_price), resale_unit_price: num(f.resale_unit_price),
                commission_basis: f.commission_basis,
                commission_pct: num(f.commission_pct),
                ship_date: f.ship_date || undefined,
              });
              setOpen(false);
              setF({ ...f, company_id: "", qty: "", value: "", commission_pct: "" });
              onSaved();
            } catch (err) {
              onError(err instanceof ApiError ? err.message : "Could not add that party.");
            } finally {
              setBusy(false);
            }
          }}
        >
          Add to chain
        </Button>
        <Button size="sm" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </div>
  );
}

function AddMilestone({
  dealId, onSaved, onError,
}: { dealId: string; onSaved: () => void; onError: (m: string) => void }) {
  const [name, setName] = React.useState("");
  const [when, setWhen] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  return (
    <div className="flex flex-wrap items-end gap-2 border-t px-5 py-3" style={{ borderColor: "var(--border)" }}>
      <Field label="Add a follow-up">
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Chemistry shipped from Osaka"
          className="w-72"
        />
      </Field>
      <Field label="Due">
        <Input type="date" value={when} onChange={(e) => setWhen(e.target.value)} className="w-40" />
      </Field>
      <Button
        size="sm"
        loading={busy}
        disabled={name.trim().length < 2}
        onClick={async () => {
          setBusy(true);
          try {
            await api.post(`/deals/${dealId}/milestones`, {
              name, planned_date: when || undefined,
            });
            setName(""); setWhen(""); onSaved();
          } catch (err) {
            onError(err instanceof ApiError ? err.message : "Could not add that.");
          } finally {
            setBusy(false);
          }
        }}
      >
        Add
      </Button>
    </div>
  );
}

function Upload({
  dealId, onSaved, onError,
}: { dealId: string; onSaved: () => void; onError: (m: string) => void }) {
  const [busy, setBusy] = React.useState(false);
  const [kind, setKind] = React.useState("PURCHASE_ORDER");

  return (
    <div className="space-y-2 border-t px-4 py-3" style={{ borderColor: "var(--border)" }}>
      <Field label="Filing it as">
        <Select value={kind} onChange={(e) => setKind(e.target.value)}>
          {["PURCHASE_ORDER", "INVOICE", "PACKING_LIST", "CONTRACT", "CERTIFICATE",
            "TEST_REPORT", "PHOTO", "OTHER"].map((k) => (
            <option key={k} value={k}>{titleCase(k)}</option>
          ))}
        </Select>
      </Field>
      <FileUpload
        label="Add to this folder"
        busy={busy}
        onFile={async (file) => {
          setBusy(true);
          try {
            const form = new FormData();
            form.append("file", file);
            form.append("kind", kind);
            form.append("deal_id", dealId);
            await uploadFile(form);
            onSaved();
          } catch (err) {
            onError(err instanceof ApiError ? err.message : "Upload failed.");
          } finally {
            setBusy(false);
          }
        }}
      />
    </div>
  );
}
