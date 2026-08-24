"use client";

import * as React from "react";
import { useParams } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { PageHeader, SourceBadge } from "@/components/AppShell";
import { TaxonomyPicker } from "@/components/TaxonomyPicker";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  CompletenessBar,
  EmptyState,
  Field,
  Input,
  Select,
  Table,
  Td,
  Textarea,
  Th,
} from "@/components/ui";
import { formatDate, formatNumber, statusTone, titleCase } from "@/lib/format";
import type {
  Certification,
  Completeness,
  Organization,
  ReferenceItem,
  SupplierCapability,
  SupplierProcess,
  SupplierProfile,
} from "@/lib/types";

const UOMS = ["PCS", "KG", "METRES", "YARDS", "DOZENS"];

// Plain-English labels for the completeness checks, and what each one unlocks. "process_moq"
// means nothing to a merchandiser; "Minimum order quantity" does.
const CHECK_LABELS: Record<string, string> = {
  identity: "Legal name",
  location: "City and country",
  contact: "A contact person",
  primary_process: "At least one process",
  primary_category: "At least one product category",
  unit_photo: "A photo of the unit",
  process_capacity: "Monthly capacity per process",
  process_moq: "Minimum order quantity per process",
  lead_times: "Standard lead times",
  capability_detail: "Fibres and GSM range per category",
  machinery: "Machinery list",
  tax_identity: "GST or PAN",
  certifications: "At least one certificate",
  compliance_or_references: "An audit report or a past-work reference",
};

const CAN_VERIFY = ["INTERNAL_SUPER_ADMIN", "INTERNAL_SOURCING_HEAD", "INTERNAL_QA"];

// The tier and the verification status are different things, and "TIER_3_VERIFIED" rendered
// next to a VERIFIED status badge reads as the same word twice. Name what the tier unlocks.
const TIER_LABELS: Record<string, string> = {
  TIER_1_REGISTERED: "Tier 1",
  TIER_2_PROFILED: "Tier 2",
  TIER_3_VERIFIED: "Tier 3",
};

const TIER_MEANING: Record<string, string> = {
  TIER_1_REGISTERED: "Registered. Not yet complete enough to take part in RFQs.",
  TIER_2_PROFILED: "Profiled — capacity, MOQ and lead times are on file. Can take part in RFQs.",
  TIER_3_VERIFIED: "Verified and brand-facing.",
};

export default function SupplierDetail() {
  const { id } = useParams<{ id: string }>();
  const { user } = useSession();
  const [banner, setBanner] = React.useState<{ tone: "emerald" | "rose"; text: string } | null>(null);

  const org = useAsync(() => api.get<Organization>(`/organizations/${id}`), [id]);
  const profile = useAsync(() => api.get<SupplierProfile>(`/suppliers/${id}/profile`), [id]);
  const completeness = useAsync(() => api.get<Completeness>(`/suppliers/${id}/completeness`), [id]);
  const processes = useAsync(() => api.get<SupplierProcess[]>(`/suppliers/${id}/processes`), [id]);
  const capabilities = useAsync(
    () => api.get<SupplierCapability[]>(`/suppliers/${id}/capabilities`),
    [id],
  );
  const certifications = useAsync(
    () => api.get<Certification[]>(`/suppliers/${id}/certifications`),
    [id],
  );

  // The taxonomy is small enough to hold entirely; resolving ids to names client-side keeps the
  // API responses lean and avoids a join per row.
  const processTypes = useAsync(
    () => api.get<ReferenceItem[]>("/master-data/items", { domain: "PROCESS_TYPE" }),
    [],
  );
  const productCategories = useAsync(
    () => api.get<ReferenceItem[]>("/master-data/items", { domain: "PRODUCT_CATEGORY" }),
    [],
  );
  const certificationTypes = useAsync(
    () => api.get<ReferenceItem[]>("/master-data/items", { domain: "CERTIFICATION" }),
    [],
  );

  const nameOf = (items: ReferenceItem[] | null, refId: string) =>
    items?.find((i) => i.id === refId)?.name ?? "—";

  function reloadAll() {
    org.reload();
    profile.reload();
    completeness.reload();
    processes.reload();
    capabilities.reload();
    certifications.reload();
  }

  async function decide(decision: string, requestedItems: string[] = [], notes?: string) {
    try {
      await api.post(`/organizations/${id}/verification`, {
        decision,
        notes,
        requested_items: requestedItems,
      });
      setBanner({ tone: "emerald", text: `Status set to ${titleCase(decision)}.` });
      reloadAll();
    } catch (err) {
      setBanner({
        tone: "rose",
        text: err instanceof ApiError ? err.message : "Could not update the status.",
      });
    }
  }

  if (org.error) return <Alert>{org.error}</Alert>;
  if (!org.data) return <EmptyState title="Loading…" />;

  const canVerify = user ? CAN_VERIFY.includes(user.role) : false;

  return (
    <>
      <PageHeader
        title={org.data.trade_name || org.data.legal_name}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(org.data.status)}>{titleCase(org.data.status)}</Badge>
            {profile.data ? (
              <Badge
                tone={profile.data.completeness_tier === "TIER_3_VERIFIED" ? "emerald" : "slate"}
                title={TIER_MEANING[profile.data.completeness_tier]}
              >
                {TIER_LABELS[profile.data.completeness_tier]}
              </Badge>
            ) : null}
            <span>{[org.data.city, org.data.state].filter(Boolean).join(", ")}</span>
            {org.data.created_by_internal ? (
              <Badge title="This profile was keyed in by our team, not filled in by the factory.">
                Assisted onboarding
              </Badge>
            ) : null}
          </span>
        }
        actions={
          canVerify ? (
            <VerificationActions status={org.data.status} onDecide={decide} />
          ) : (
            <Badge title="Verification requires a Sourcing Head or QA role.">View only</Badge>
          )
        }
      />

      {banner ? (
        <div className="mb-4">
          <Alert tone={banner.tone}>{banner.text}</Alert>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <div className="space-y-5">
          <Card>
            <CardHeader
              title="Processes"
              subtitle="Capacity and MOQ are what make this factory findable — without them it is filtered out of every search"
            />
            {(processes.data?.length ?? 0) === 0 ? (
              <EmptyState title="No processes recorded" />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Process</Th>
                    <Th align="right">Monthly capacity</Th>
                    <Th align="right">MOQ</Th>
                    <Th align="right">Lead time</Th>
                    <Th align="right">Sample</Th>
                    <Th>Source</Th>
                  </tr>
                </thead>
                <tbody>
                  {processes.data?.map((row) => (
                    <tr key={row.id}>
                      <Td>
                        <span className="font-medium">
                          {nameOf(processTypes.data, row.process_type_id)}
                        </span>
                        {row.is_subcontracted ? (
                          <Badge tone="amber" title="Not done in-house">
                            Subcontracted
                          </Badge>
                        ) : null}
                      </Td>
                      <Td align="right">
                        {row.monthly_capacity_value === null ? (
                          <Missing />
                        ) : (
                          `${formatNumber(row.monthly_capacity_value)} ${row.capacity_uom ?? ""}`
                        )}
                      </Td>
                      <Td align="right">
                        {row.min_order_qty === null ? (
                          <Missing />
                        ) : (
                          `${formatNumber(row.min_order_qty)} ${row.moq_uom ?? ""}`
                        )}
                      </Td>
                      <Td align="right">
                        {row.standard_lead_time_days ? `${row.standard_lead_time_days} d` : <Missing />}
                      </Td>
                      <Td align="right">
                        {row.sample_lead_time_days ? `${row.sample_lead_time_days} d` : <Missing />}
                      </Td>
                      <Td>
                        <SourceBadge source={row.source} />
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            <ProcessEditor orgId={id} onSaved={reloadAll} />
          </Card>

          <Card>
            <CardHeader title="Capabilities" subtitle="What they can actually make, per category" />
            {(capabilities.data?.length ?? 0) === 0 ? (
              <EmptyState title="No capabilities recorded" />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Category</Th>
                    <Th align="right">GSM range</Th>
                    <Th align="right">Price band</Th>
                    <Th>Source</Th>
                  </tr>
                </thead>
                <tbody>
                  {capabilities.data?.map((row) => (
                    <tr key={row.id}>
                      <Td className="font-medium">
                        {nameOf(productCategories.data, row.product_category_id)}
                      </Td>
                      <Td align="right">
                        {row.gsm_min || row.gsm_max ? (
                          `${row.gsm_min ?? "?"}–${row.gsm_max ?? "?"}`
                        ) : (
                          <Missing />
                        )}
                      </Td>
                      <Td align="right">
                        {row.price_band_min || row.price_band_max ? (
                          `${row.price_band_min ?? "?"}–${row.price_band_max ?? "?"}`
                        ) : (
                          // Not a gating field — a missing price band narrows nothing, so it
                          // does not get the warning treatment that a missing MOQ does.
                          <span style={{ color: "var(--text-subtle)" }}>—</span>
                        )}
                      </Td>
                      <Td>
                        <SourceBadge source={row.source} />
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>

          <Card>
            <CardHeader
              title="Certifications"
              subtitle="Only verified, unexpired certificates satisfy a buyer's requirement"
            />
            {(certifications.data?.length ?? 0) === 0 ? (
              <EmptyState title="No certificates on file" />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Certificate</Th>
                    <Th>Number</Th>
                    <Th>Valid till</Th>
                    <Th>Status</Th>
                  </tr>
                </thead>
                <tbody>
                  {certifications.data?.map((row) => {
                    const expired = row.valid_till ? new Date(row.valid_till) < new Date() : false;
                    return (
                      <tr key={row.id}>
                        <Td className="font-medium">
                          {nameOf(certificationTypes.data, row.certification_id)}
                        </Td>
                        <Td>{row.certificate_no ?? "—"}</Td>
                        <Td>
                          <span style={{ color: expired ? "var(--danger)" : undefined }}>
                            {formatDate(row.valid_till)}
                          </span>
                        </Td>
                        <Td>
                          <Badge tone={expired ? "rose" : statusTone(row.verification_status)}>
                            {expired ? "Expired" : titleCase(row.verification_status)}
                          </Badge>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            )}
          </Card>

          <Card>
            <CardHeader
              title="What they are known for"
              subtitle="The one free-text answer we keep — it is what the matching engine will read for nuance the fields miss"
            />
            <NarrativeEditor
              orgId={id}
              initial={profile.data?.capability_narrative ?? ""}
              onSaved={reloadAll}
            />
          </Card>
        </div>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Profile completeness" />
            <div className="px-5 py-4">
              <CompletenessBar value={completeness.data?.completeness_pct ?? 0} />
              <p className="mt-3 text-xs" style={{ color: "var(--text-muted)" }}>
                An incomplete profile is invisible to the matching engine. These are the gaps.
              </p>
              <ul className="mt-3 space-y-1.5">
                {Object.entries(completeness.data?.checks ?? {}).map(([key, passed]) => (
                  <li key={key} className="flex items-start gap-2 text-xs">
                    <span
                      aria-hidden
                      className="mt-0.5 inline-block h-3 w-3 shrink-0 rounded-full"
                      style={{ background: passed ? "var(--success)" : "var(--border-strong)" }}
                    />
                    <span style={{ color: passed ? "var(--text-muted)" : "var(--text)" }}>
                      {CHECK_LABELS[key] ?? key}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </Card>

          <Card>
            <CardHeader title="Getting them to finish it" />
            <div className="space-y-3 px-5 py-4">
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                Send a link they can open on their phone and continue from where they stopped.
                Nothing already entered is lost.
              </p>
              <ResumeLinkButton orgId={id} />
            </div>
          </Card>

          <Card>
            <CardHeader title="Registration" />
            <dl className="space-y-2 px-5 py-4 text-xs">
              {[
                ["Legal name", org.data.legal_name],
                ["Registered", formatDate(org.data.created_at)],
                ["Website", org.data.website ?? "—"],
                ["Established", org.data.year_established?.toString() ?? "—"],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-3">
                  <dt style={{ color: "var(--text-subtle)" }}>{label}</dt>
                  <dd className="text-right">{value}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      </div>
    </>
  );
}

function Missing() {
  return (
    <span title="Missing — this filters the supplier out of searches" style={{ color: "var(--warning)" }}>
      not set
    </span>
  );
}

function VerificationActions({
  status,
  onDecide,
}: {
  status: string;
  onDecide: (decision: string, requestedItems?: string[], notes?: string) => Promise<void>;
}) {
  const [asking, setAsking] = React.useState(false);
  const [items, setItems] = React.useState("");

  if (asking) {
    return (
      <div className="flex items-end gap-2">
        <Field label="What do you still need?" hint="One per line — 'incomplete' is not actionable">
          <Textarea
            rows={2}
            className="w-72"
            value={items}
            onChange={(e) => setItems(e.target.value)}
            placeholder={"GOTS scope certificate\nGST registration"}
          />
        </Field>
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            const list = items.split("\n").map((l) => l.trim()).filter(Boolean);
            if (list.length) void onDecide("NEEDS_INFO", list).then(() => setAsking(false));
          }}
        >
          Send
        </Button>
        <Button size="sm" onClick={() => setAsking(false)}>
          Cancel
        </Button>
      </div>
    );
  }

  return (
    <>
      {status !== "VERIFIED" ? (
        <Button size="sm" variant="primary" onClick={() => void onDecide("VERIFIED")}>
          Verify
        </Button>
      ) : (
        <Button size="sm" onClick={() => void onDecide("SUSPENDED")}>
          Suspend
        </Button>
      )}
      <Button size="sm" onClick={() => setAsking(true)}>
        Request info
      </Button>
    </>
  );
}

function ProcessEditor({ orgId, onSaved }: { orgId: string; onSaved: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [form, setForm] = React.useState({
    process_code: "",
    monthly_capacity_value: "",
    capacity_uom: "PCS",
    min_order_qty: "",
    moq_uom: "PCS",
    standard_lead_time_days: "",
    sample_lead_time_days: "",
  });

  if (!open) {
    return (
      <div className="border-t px-5 py-3" style={{ borderColor: "var(--border)" }}>
        <Button size="sm" onClick={() => setOpen(true)}>
          Add or update a process
        </Button>
      </div>
    );
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.put(`/suppliers/${orgId}/processes`, {
        process_code: form.process_code,
        // Send undefined rather than null for blanks: a capacity with no unit is rejected by
        // the database, and an empty string would become one.
        monthly_capacity_value: form.monthly_capacity_value
          ? Number(form.monthly_capacity_value)
          : undefined,
        capacity_uom: form.monthly_capacity_value ? form.capacity_uom : undefined,
        min_order_qty: form.min_order_qty ? Number(form.min_order_qty) : undefined,
        moq_uom: form.min_order_qty ? form.moq_uom : undefined,
        standard_lead_time_days: form.standard_lead_time_days
          ? Number(form.standard_lead_time_days)
          : undefined,
        sample_lead_time_days: form.sample_lead_time_days
          ? Number(form.sample_lead_time_days)
          : undefined,
      });
      setOpen(false);
      setForm({ ...form, process_code: "", monthly_capacity_value: "", min_order_qty: "" });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border-t px-5 py-4" style={{ borderColor: "var(--border)" }}>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="sm:col-span-3">
          <Field label="Process" required>
            <TaxonomyPicker
              domain="PROCESS_TYPE"
              value={form.process_code}
              onChange={(code) => setForm((f) => ({ ...f, process_code: code }))}
            />
          </Field>
        </div>
        <Field label="Monthly capacity">
          <Input
            inputMode="numeric"
            value={form.monthly_capacity_value}
            onChange={(e) =>
              setForm((f) => ({ ...f, monthly_capacity_value: e.target.value.replace(/[^\d.]/g, "") }))
            }
          />
        </Field>
        <Field label="Capacity unit">
          <Select
            value={form.capacity_uom}
            onChange={(e) => setForm((f) => ({ ...f, capacity_uom: e.target.value }))}
          >
            {UOMS.map((u) => (
              <option key={u}>{u}</option>
            ))}
          </Select>
        </Field>
        <Field label="Lead time (days)">
          <Input
            inputMode="numeric"
            value={form.standard_lead_time_days}
            onChange={(e) =>
              setForm((f) => ({ ...f, standard_lead_time_days: e.target.value.replace(/\D/g, "") }))
            }
          />
        </Field>
        <Field label="Minimum order">
          <Input
            inputMode="numeric"
            value={form.min_order_qty}
            onChange={(e) =>
              setForm((f) => ({ ...f, min_order_qty: e.target.value.replace(/[^\d.]/g, "") }))
            }
          />
        </Field>
        <Field label="MOQ unit">
          <Select
            value={form.moq_uom}
            onChange={(e) => setForm((f) => ({ ...f, moq_uom: e.target.value }))}
          >
            {UOMS.map((u) => (
              <option key={u}>{u}</option>
            ))}
          </Select>
        </Field>
        <Field label="Sample lead time (days)">
          <Input
            inputMode="numeric"
            value={form.sample_lead_time_days}
            onChange={(e) =>
              setForm((f) => ({ ...f, sample_lead_time_days: e.target.value.replace(/\D/g, "") }))
            }
          />
        </Field>
      </div>

      {error ? (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      <div className="mt-3 flex gap-2">
        <Button
          size="sm"
          variant="primary"
          loading={busy}
          disabled={!form.process_code}
          onClick={() => void save()}
        >
          Save process
        </Button>
        <Button size="sm" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function NarrativeEditor({
  orgId,
  initial,
  onSaved,
}: {
  orgId: string;
  initial: string;
  onSaved: () => void;
}) {
  const [value, setValue] = React.useState(initial);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // The narrative arrives after the first render. Adjusting state during render is React's
  // documented answer to "reset state when a prop changes" — an effect for this causes an
  // extra render pass and would clobber what the user is typing on every parent refresh.
  const [lastInitial, setLastInitial] = React.useState(initial);
  if (initial !== lastInitial) {
    setLastInitial(initial);
    setValue(initial);
  }

  return (
    <div className="px-5 py-4">
      <Textarea
        rows={4}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="e.g. Heavy-GSM french terry with reactive dyeing; strong on oversized silhouettes and garment-dyed finishes for European buyers."
      />
      {error ? (
        <div className="mt-2">
          <Alert>{error}</Alert>
        </div>
      ) : null}
      <div className="mt-2 flex items-center justify-between gap-3">
        <p className="text-xs" style={{ color: "var(--text-subtle)" }}>
          At least 20 characters. Everything else on this page is a dropdown for a reason — this
          field is the exception.
        </p>
        <Button
          size="sm"
          variant="primary"
          loading={busy}
          disabled={value.trim().length < 20}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await api.put(`/suppliers/${orgId}/narrative`, { capability_narrative: value });
              onSaved();
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "Could not save.");
            } finally {
              setBusy(false);
            }
          }}
        >
          Save
        </Button>
      </div>
    </div>
  );
}

function ResumeLinkButton({ orgId }: { orgId: string }) {
  const [link, setLink] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  return (
    <div className="space-y-2">
      <Button
        size="sm"
        loading={busy}
        onClick={async () => {
          setBusy(true);
          try {
            const result = await api.get<{ detail: string }>(`/organizations/${orgId}/resume-link`);
            setLink(result.detail);
          } finally {
            setBusy(false);
          }
        }}
      >
        Send a continue link over WhatsApp
      </Button>
      {link ? (
        <p className="font-mono text-[11px] break-all" style={{ color: "var(--text-subtle)" }}>
          {link}
        </p>
      ) : null}
    </div>
  );
}
