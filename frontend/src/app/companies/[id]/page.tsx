"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ApiError, api, uploadFile } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { useRequireSession } from "@/lib/session";
import { AppShell, PageHeader } from "@/components/AppShell";
import { DocumentRow } from "@/components/DocumentRow";
import { Alert, Badge, Button, Card, CardHeader, EmptyState, Field, FileUpload, Input, Select, StatusBadge, Table, Td, Textarea, Th } from "@/components/ui";
import { formatDate, money, titleCase } from "@/lib/format";
import type { CompanyDetail, DealRow, DocRow, Ref } from "@/lib/types";

export default function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const { user, loading } = useRequireSession();
  const company = useAsync(() => api.get<CompanyDetail>(`/companies/${id}`), [id]);
  const deals = useAsync(() => api.get<DealRow[]>("/deals", { company_id: id }), [id]);
  const files = useAsync(() => api.get<DocRow[]>("/documents", { company_id: id }), [id]);
  const [banner, setBanner] = React.useState<string | null>(null);

  if (loading || !user) return null;
  if (company.error) return <AppShell><Alert>{company.error}</Alert></AppShell>;
  if (!company.data) return <AppShell><EmptyState title="Loading…" /></AppShell>;

  const c = company.data;
  const reload = () => { company.reload(); files.reload(); };

  return (
    <AppShell>
      <PageHeader
        title={c.name}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            {c.sells ? <Badge tone="emerald">Sells to us</Badge> : null}
            {c.buys ? <Badge tone="sky">Buys from us</Badge> : null}
            <StatusBadge status={c.status} />
            <span>{c.city ?? "—"}</span>
            {c.open_deals ? <span>· {c.open_deals} open deal{c.open_deals === 1 ? "" : "s"}</span> : null}
          </span>
        }
      />

      {banner ? <div className="mb-4"><Alert>{banner}</Alert></div> : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <div className="space-y-5">
          <Card>
            <CardHeader
              title="What they do"
              subtitle="The searchable layer — the detail lives in the brochure"
            />
            <div className="grid gap-4 p-5 sm:grid-cols-3">
              <Tags label="Processes" values={c.processes} />
              <Tags label="Products" values={c.products} />
              <Tags label="Certifications" values={c.certifications} tone="emerald" />
            </div>
            <AddTags companyId={id} onSaved={reload} onError={setBanner} />
          </Card>

          <Card>
            <CardHeader title="Capacity, machinery and terms" />
            <dl className="grid gap-4 p-5 sm:grid-cols-2">
              {[
                ["Capacity", c.capacity_notes],
                ["Machinery", c.machinery_notes],
                ["Minimum order", c.moq_notes],
                ["Lead time", c.lead_time_notes],
                ["Payment terms", c.payment_terms],
                ["Quality requirements", c.quality_requirements],
              ].map(([label, value]) => (
                <div key={label as string}>
                  <dt className="text-[11px] tracking-wide uppercase"
                      style={{ color: "var(--text-subtle)" }}>{label}</dt>
                  <dd className="mt-0.5 text-sm">
                    {value || <span style={{ color: "var(--text-subtle)" }}>—</span>}
                  </dd>
                </div>
              ))}
            </dl>
            <EditNotes company={c} onSaved={reload} onError={setBanner} />
          </Card>

          <Card>
            <CardHeader title="Deals" subtitle="Every deal this company is on, in any role" />
            {(deals.data?.length ?? 0) === 0 ? (
              <EmptyState title="Not on a deal yet" />
            ) : (
              <Table>
                <thead>
                  <tr><Th>Deal</Th><Th>Status</Th><Th align="right">Value</Th><Th>Ships</Th></tr>
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
                      <Td><StatusBadge status={d.status} /></Td>
                      <Td align="right">{money(d.value)}</Td>
                      <Td>{formatDate(d.target_ship_date)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Contacts" />
            {c.contacts.length === 0 ? (
              <EmptyState title="No contacts yet" />
            ) : (
              <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                {c.contacts.map((p) => (
                  <li key={p.id} className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{p.name}</span>
                      {p.is_primary ? <Badge tone="sky">Primary</Badge> : null}
                    </div>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                      {[p.designation, p.phone, p.email].filter(Boolean).join(" · ")}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <AddContact companyId={id} onSaved={reload} onError={setBanner} />
          </Card>

          <Card>
            <CardHeader
              title="Files"
              subtitle="The factory brochure and anything else about them"
            />
            {(files.data?.length ?? 0) === 0 ? (
              <EmptyState title="No files yet" hint="Upload the factory brochure PDF here." />
            ) : (
              <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                {files.data?.map((doc) => (
                  <DocumentRow key={doc.id} doc={doc} onDeleted={() => files.reload()}
                               onError={setBanner} />
                ))}
              </ul>
            )}
            <UploadFile companyId={id} onSaved={reload} onError={setBanner} />
          </Card>

          {c.clients.length ? (
            <Card>
              <CardHeader title="Brands they work for" />
              <div className="flex flex-wrap gap-1 px-5 py-4">
                {c.clients.map((name) => <Badge key={name}>{name}</Badge>)}
              </div>
            </Card>
          ) : null}
        </div>
      </div>
    </AppShell>
  );
}

function Tags({ label, values, tone = "slate" }: { label: string; values: string[]; tone?: string }) {
  return (
    <div>
      <div className="mb-1.5 text-[11px] tracking-wide uppercase" style={{ color: "var(--text-subtle)" }}>
        {label}
      </div>
      {values.length === 0 ? (
        <span className="text-sm" style={{ color: "var(--text-subtle)" }}>—</span>
      ) : (
        <div className="flex flex-wrap gap-1">
          {values.map((v) => <Badge key={v} tone={tone}>{v}</Badge>)}
        </div>
      )}
    </div>
  );
}

function AddTags({
  companyId, onSaved, onError,
}: { companyId: string; onSaved: () => void; onError: (m: string) => void }) {
  const [domain, setDomain] = React.useState<"PROCESS" | "PRODUCT" | "CERTIFICATION">("PROCESS");
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const options = useAsync(() => api.get<Ref[]>("/taxonomy", { domain }), [domain]);

  const path = { PROCESS: "processes", PRODUCT: "products", CERTIFICATION: "certifications" }[domain];

  return (
    <div className="flex flex-wrap items-end gap-2 border-t px-5 py-3" style={{ borderColor: "var(--border)" }}>
      <Field label="Add">
        <Select
          value={domain}
          onChange={(e) => { setDomain(e.target.value as typeof domain); setCode(""); }}
          className="w-40"
        >
          <option value="PROCESS">A process</option>
          <option value="PRODUCT">A product</option>
          <option value="CERTIFICATION">A certification</option>
        </Select>
      </Field>
      <Field label="Which">
        <Select value={code} onChange={(e) => setCode(e.target.value)} className="w-56">
          <option value="">Choose…</option>
          {options.data?.map((o) => <option key={o.id} value={o.code}>{o.name}</option>)}
        </Select>
      </Field>
      <Button
        size="sm"
        loading={busy}
        disabled={!code}
        onClick={async () => {
          setBusy(true);
          try {
            if (domain === "PROCESS") {
              await api.put(`/companies/${companyId}/processes`, { process_code: code });
            } else {
              await api.post(`/companies/${companyId}/${path}`, { code });
            }
            setCode("");
            onSaved();
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

function AddContact({
  companyId, onSaved, onError,
}: { companyId: string; onSaved: () => void; onError: (m: string) => void }) {
  const [f, setF] = React.useState({ name: "", designation: "", phone: "", email: "" });
  const [busy, setBusy] = React.useState(false);

  return (
    <div className="grid gap-2 border-t px-4 py-3" style={{ borderColor: "var(--border)" }}>
      <Input placeholder="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
      <div className="grid grid-cols-2 gap-2">
        <Input placeholder="Role" value={f.designation}
               onChange={(e) => setF({ ...f, designation: e.target.value })} />
        <Input placeholder="Phone" value={f.phone}
               onChange={(e) => setF({ ...f, phone: e.target.value })} />
      </div>
      <Input placeholder="Email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
      <Button
        size="sm"
        loading={busy}
        disabled={f.name.trim().length < 2}
        onClick={async () => {
          setBusy(true);
          try {
            await api.post(`/companies/${companyId}/contacts`, {
              name: f.name, designation: f.designation || undefined,
              phone: f.phone || undefined, email: f.email || undefined,
              whatsapp: f.phone || undefined, is_primary: false,
            });
            setF({ name: "", designation: "", phone: "", email: "" });
            onSaved();
          } catch (err) {
            onError(err instanceof ApiError ? err.message : "Could not add that contact.");
          } finally {
            setBusy(false);
          }
        }}
      >
        Add contact
      </Button>
    </div>
  );
}

function EditNotes({
  company, onSaved, onError,
}: { company: CompanyDetail; onSaved: () => void; onError: (m: string) => void }) {
  const [open, setOpen] = React.useState(false);
  const [f, setF] = React.useState({
    capacity_notes: company.capacity_notes ?? "",
    machinery_notes: company.machinery_notes ?? "",
    moq_notes: company.moq_notes ?? "",
    lead_time_notes: company.lead_time_notes ?? "",
    payment_terms: company.payment_terms ?? "",
    quality_requirements: company.quality_requirements ?? "",
  });
  const [busy, setBusy] = React.useState(false);

  if (!open) {
    return (
      <div className="border-t px-5 py-3" style={{ borderColor: "var(--border)" }}>
        <Button size="sm" onClick={() => setOpen(true)}>Edit these</Button>
      </div>
    );
  }

  return (
    <div className="grid gap-3 border-t px-5 py-4 sm:grid-cols-2" style={{ borderColor: "var(--border)" }}>
      {([
        ["capacity_notes", "Capacity"], ["machinery_notes", "Machinery"],
        ["moq_notes", "Minimum order"], ["lead_time_notes", "Lead time"],
        ["payment_terms", "Payment terms"], ["quality_requirements", "Quality requirements"],
      ] as const).map(([key, label]) => (
        <Field key={key} label={label}>
          <Textarea rows={2} value={f[key]} onChange={(e) => setF({ ...f, [key]: e.target.value })} />
        </Field>
      ))}
      <div className="flex gap-2 sm:col-span-2">
        <Button
          size="sm"
          variant="primary"
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api.patch(`/companies/${company.id}`, { name: company.name, ...f });
              setOpen(false);
              onSaved();
            } catch (err) {
              onError(err instanceof ApiError ? err.message : "Could not save.");
            } finally {
              setBusy(false);
            }
          }}
        >
          Save
        </Button>
        <Button size="sm" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </div>
  );
}

function UploadFile({
  companyId, onSaved, onError,
}: { companyId: string; onSaved: () => void; onError: (m: string) => void }) {
  const [kind, setKind] = React.useState("BROCHURE");
  const [busy, setBusy] = React.useState(false);

  return (
    <div className="space-y-2 border-t px-4 py-3" style={{ borderColor: "var(--border)" }}>
      <Field label="Filing it as">
        <Select value={kind} onChange={(e) => setKind(e.target.value)}>
          {["BROCHURE", "CERTIFICATE", "CONTRACT", "PHOTO", "OTHER"].map((k) => (
            <option key={k} value={k}>{titleCase(k)}</option>
          ))}
        </Select>
      </Field>
      <FileUpload
        label={kind === "BROCHURE" ? "Upload the brochure" : "Upload a file"}
        busy={busy}
        onFile={async (file) => {
          setBusy(true);
          try {
            const form = new FormData();
            form.append("file", file);
            form.append("kind", kind);
            form.append("company_id", companyId);
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
