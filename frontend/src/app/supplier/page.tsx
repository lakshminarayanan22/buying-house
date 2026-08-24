"use client";

import * as React from "react";

import { ApiError, api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/AppShell";
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
  Th,
} from "@/components/ui";
import { formatNumber, statusTone, titleCase } from "@/lib/format";
import type { Completeness, ReferenceItem, SupplierProcess } from "@/lib/types";

const UOMS = ["PCS", "KG", "METRES", "YARDS", "DOZENS"];

// What each gap costs the supplier, in their terms. "Add capacity" is an instruction;
// "buyers filter on this" is a reason.
const WHY: Record<string, string> = {
  process_capacity: "Buyers filter by how much you can make each month.",
  process_moq: "Without a minimum order, you are excluded from every quantity filter.",
  lead_times: "Buyers with a ship date need to know your lead time.",
  capability_detail: "Fibres and GSM decide which enquiries reach you.",
  unit_photo: "A photo of the unit makes your profile credible.",
  machinery: "Your machine list is how buyers judge what you can handle.",
  tax_identity: "GST or PAN is needed before we can place an order with you.",
  certifications: "Certified buyers can only work with certified factories.",
  compliance_or_references: "An audit report or a past buyer helps us vouch for you.",
};

/**
 * The supplier's own portal.
 *
 * §11: suppliers stop updating a system that gives them nothing back. So this screen leads with
 * what they get — visibility to buyers — and states plainly what each missing field costs them,
 * rather than showing a percentage and hoping they care.
 */
export default function MyProfile() {
  const { user } = useSession();
  const orgId = user?.org_id;

  const completeness = useAsync(
    () => (orgId ? api.get<Completeness>(`/suppliers/${orgId}/completeness`) : Promise.resolve(null)),
    [orgId],
  );
  const processes = useAsync(
    () => (orgId ? api.get<SupplierProcess[]>(`/suppliers/${orgId}/processes`) : Promise.resolve([])),
    [orgId],
  );
  const processTypes = useAsync(
    () => api.get<ReferenceItem[]>("/master-data/items", { domain: "PROCESS_TYPE" }),
    [],
  );

  const [banner, setBanner] = React.useState<{ tone: "emerald" | "rose"; text: string } | null>(null);

  if (!orgId) return <EmptyState title="No organisation linked to this account" />;

  const missing = completeness.data?.missing ?? [];
  const pct = completeness.data?.completeness_pct ?? 0;

  async function submit() {
    try {
      await api.post(`/suppliers/${orgId}/submit`);
      setBanner({ tone: "emerald", text: "Sent to our team for review. We will be in touch." });
      completeness.reload();
    } catch (err) {
      setBanner({
        tone: "rose",
        text: err instanceof ApiError ? err.message : "Could not submit just yet.",
      });
    }
  }

  return (
    <>
      <PageHeader
        title={user?.org_name ?? "My profile"}
        subtitle={
          <span className="flex items-center gap-2">
            <Badge tone={statusTone(user?.org_status)}>{titleCase(user?.org_status)}</Badge>
            <CompletenessBar value={pct} />
          </span>
        }
        actions={
          <Button variant="primary" onClick={() => void submit()}>
            Send for review
          </Button>
        }
      />

      {banner ? (
        <div className="mb-4">
          <Alert tone={banner.tone}>{banner.text}</Alert>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
        <Card>
          <CardHeader
            title="What you make"
            subtitle="Capacity and minimum order for each process. These are the numbers buyers search on."
          />
          {(processes.data?.length ?? 0) === 0 ? (
            <EmptyState title="No processes added yet" />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Process</Th>
                  <Th align="right">Per month</Th>
                  <Th align="right">Minimum order</Th>
                  <Th align="right">Lead time</Th>
                </tr>
              </thead>
              <tbody>
                {processes.data?.map((row) => (
                  <tr key={row.id}>
                    <Td className="font-medium">
                      {processTypes.data?.find((p) => p.id === row.process_type_id)?.name ?? "—"}
                    </Td>
                    <Td align="right">
                      {row.monthly_capacity_value === null
                        ? "—"
                        : `${formatNumber(row.monthly_capacity_value)} ${row.capacity_uom ?? ""}`}
                    </Td>
                    <Td align="right">
                      {row.min_order_qty === null
                        ? "—"
                        : `${formatNumber(row.min_order_qty)} ${row.moq_uom ?? ""}`}
                    </Td>
                    <Td align="right">
                      {row.standard_lead_time_days ? `${row.standard_lead_time_days} days` : "—"}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          <QuickProcessForm
            orgId={orgId}
            onSaved={() => {
              processes.reload();
              completeness.reload();
            }}
          />
        </Card>

        <Card>
          <CardHeader
            title="Finish your profile"
            subtitle={pct >= 80 ? "Almost there." : "Each of these makes you visible to more buyers."}
          />
          {missing.length === 0 ? (
            <EmptyState title="Everything we asked for is filled in" hint="Thank you — you are fully searchable." />
          ) : (
            <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
              {missing.map((key) => (
                <li key={key} className="px-4 py-3">
                  <div className="text-sm font-medium">{titleCase(key)}</div>
                  {WHY[key] ? (
                    <p className="mt-0.5 text-xs" style={{ color: "var(--text-muted)" }}>
                      {WHY[key]}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

function QuickProcessForm({ orgId, onSaved }: { orgId: string; onSaved: () => void }) {
  const [form, setForm] = React.useState({
    process_code: "",
    monthly_capacity_value: "",
    capacity_uom: "PCS",
    min_order_qty: "",
    moq_uom: "PCS",
    standard_lead_time_days: "",
  });
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  return (
    <div className="border-t px-5 py-4" style={{ borderColor: "var(--border)" }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Process">
            <TaxonomyPicker
              domain="PROCESS_TYPE"
              value={form.process_code}
              onChange={(code) => setForm((f) => ({ ...f, process_code: code }))}
              placeholder="Knitting, dyeing, stitching…"
            />
          </Field>
        </div>
        <Field label="How much per month">
          <Input
            inputMode="numeric"
            value={form.monthly_capacity_value}
            onChange={(e) =>
              setForm((f) => ({ ...f, monthly_capacity_value: e.target.value.replace(/[^\d.]/g, "") }))
            }
          />
        </Field>
        <Field label="Unit">
          <Select
            value={form.capacity_uom}
            onChange={(e) => setForm((f) => ({ ...f, capacity_uom: e.target.value }))}
          >
            {UOMS.map((u) => (
              <option key={u}>{u}</option>
            ))}
          </Select>
        </Field>
        <Field label="Smallest order you accept">
          <Input
            inputMode="numeric"
            value={form.min_order_qty}
            onChange={(e) =>
              setForm((f) => ({ ...f, min_order_qty: e.target.value.replace(/[^\d.]/g, "") }))
            }
          />
        </Field>
        <Field label="Unit">
          <Select
            value={form.moq_uom}
            onChange={(e) => setForm((f) => ({ ...f, moq_uom: e.target.value }))}
          >
            {UOMS.map((u) => (
              <option key={u}>{u}</option>
            ))}
          </Select>
        </Field>
        <Field label="Usual lead time (days)">
          <Input
            inputMode="numeric"
            value={form.standard_lead_time_days}
            onChange={(e) =>
              setForm((f) => ({ ...f, standard_lead_time_days: e.target.value.replace(/\D/g, "") }))
            }
          />
        </Field>
      </div>

      {error ? (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      <Button
        className="mt-3"
        size="sm"
        variant="primary"
        loading={busy}
        disabled={!form.process_code}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await api.put(`/suppliers/${orgId}/processes`, {
              process_code: form.process_code,
              monthly_capacity_value: form.monthly_capacity_value
                ? Number(form.monthly_capacity_value)
                : undefined,
              capacity_uom: form.monthly_capacity_value ? form.capacity_uom : undefined,
              min_order_qty: form.min_order_qty ? Number(form.min_order_qty) : undefined,
              moq_uom: form.min_order_qty ? form.moq_uom : undefined,
              standard_lead_time_days: form.standard_lead_time_days
                ? Number(form.standard_lead_time_days)
                : undefined,
            });
            setForm({ ...form, process_code: "", monthly_capacity_value: "", min_order_qty: "" });
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
  );
}
