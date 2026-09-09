"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { useAsync, useDebounced } from "@/lib/hooks";
import { useRequireSession } from "@/lib/session";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Alert, Badge, Button, Card, CardHeader, EmptyState, Field, Input, Select, StatusBadge, Table, Td, Th } from "@/components/ui";
import {  } from "@/lib/format";
import type { CompanyDetail, CompanyRow, Ref } from "@/lib/types";

export default function CompaniesPage() {
  const { user, loading } = useRequireSession();
  const [search, setSearch] = React.useState("");
  const [process, setProcess] = React.useState("");
  const [side, setSide] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const debounced = useDebounced(search);

  const processes = useAsync(() => api.get<Ref[]>("/taxonomy", { domain: "PROCESS" }), []);
  const companies = useAsync(
    () => api.get<CompanyRow[]>("/companies", {
      search: debounced || undefined,
      process: process || undefined,
      buys: side === "buys" ? true : undefined,
      sells: side === "sells" ? true : undefined,
    }),
    [debounced, process, side],
  );

  if (loading || !user) return null;

  return (
    <AppShell>
      <PageHeader
        title="Companies"
        subtitle={
          companies.data
            ? `${companies.data.length} compan${companies.data.length === 1 ? "y" : "ies"} — everyone we deal with, either side`
            : "Loading…"
        }
        actions={<Button variant="primary" onClick={() => setCreating(true)}>Add a company</Button>}
      />

      {creating ? <NewCompany onClose={() => setCreating(false)} /> : null}

      <Card rail>
        <CardHeader
          title="All companies"
          actions={
            <div className="flex flex-wrap gap-2">
              <Input
                placeholder="Name or city"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-52"
              />
              <Select value={process} onChange={(e) => setProcess(e.target.value)} className="w-48">
                <option value="">Any process</option>
                {processes.data?.map((p) => (
                  <option key={p.id} value={p.code}>{p.name}</option>
                ))}
              </Select>
              <Select value={side} onChange={(e) => setSide(e.target.value)} className="w-36">
                <option value="">Either side</option>
                <option value="sells">Sells to us</option>
                <option value="buys">Buys from us</option>
              </Select>
            </div>
          }
        />
        {companies.error ? (
          <div className="p-4"><Alert>{companies.error}</Alert></div>
        ) : companies.loading ? (
          <EmptyState title="Loading…" />
        ) : (companies.data?.length ?? 0) === 0 ? (
          <EmptyState title="No companies match" hint="Try clearing a filter." />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Company</Th><Th>Side</Th><Th>Processes</Th>
                <Th>Products</Th><Th>Certifications</Th><Th>Status</Th>
              </tr>
            </thead>
            <tbody>
              {companies.data?.map((c) => (
                <tr key={c.id}>
                  <Td>
                    <Link href={`/companies/${c.id}`} className="font-medium hover:underline">
                      {c.name}
                    </Link>
                    <div className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                      {c.city ?? "—"}
                      {c.has_brochure ? " · brochure on file" : ""}
                    </div>
                  </Td>
                  <Td>
                    <div className="flex gap-1">
                      {c.sells ? <Badge tone="emerald">Sells</Badge> : null}
                      {c.buys ? <Badge tone="sky">Buys</Badge> : null}
                    </div>
                  </Td>
                  <Td><Chips values={c.processes} /></Td>
                  <Td><Chips values={c.products} /></Td>
                  <Td><Chips values={c.certifications} tone="emerald" /></Td>
                  <Td><StatusBadge status={c.status} /></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </AppShell>
  );
}

function Chips({ values, tone = "slate" }: { values: string[]; tone?: string }) {
  if (values.length === 0) return <span style={{ color: "var(--text-subtle)" }}>—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {values.slice(0, 2).map((v) => <Badge key={v} tone={tone}>{v}</Badge>)}
      {values.length > 2 ? (
        <Badge title={values.slice(2).join(", ")}>+{values.length - 2}</Badge>
      ) : null}
    </div>
  );
}

function NewCompany({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [f, setF] = React.useState({
    name: "", city: "", country_code: "", sells: true, buys: false,
  });
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const countries = useAsync(() => api.get<Ref[]>("/taxonomy", { domain: "COUNTRY" }), []);

  return (
    <Card className="mb-5">
      <CardHeader
        title="Add a company"
        subtitle="Processes, products and certifications go on next, from the company's own page"
      />
      <form
        className="grid gap-3 p-5 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          void (async () => {
            try {
              const company = await api.post<CompanyDetail>("/companies", {
                name: f.name, city: f.city || undefined,
                country_code: f.country_code || undefined,
                sells: f.sells, buys: f.buys, status: "ACTIVE",
              });
              router.push(`/companies/${company.id}`);
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "Could not add that company.");
              setBusy(false);
            }
          })();
        }}
      >
        <Field label="Name" required>
          <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })}
                 placeholder="Sri Vaari Spinning Mills" required />
        </Field>
        <Field label="City">
          <Input value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })}
                 placeholder="Coimbatore" />
        </Field>
        <Field label="Country">
          <Select value={f.country_code} onChange={(e) => setF({ ...f, country_code: e.target.value })}>
            <option value="">—</option>
            {countries.data?.map((c) => <option key={c.id} value={c.code}>{c.name}</option>)}
          </Select>
        </Field>
        <Field label="Which way do they trade?" hint="A spinning mill does both">
          <div className="flex gap-4 pt-1.5 text-sm">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={f.sells}
                     onChange={(e) => setF({ ...f, sells: e.target.checked })} />
              Sells to us
            </label>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={f.buys}
                     onChange={(e) => setF({ ...f, buys: e.target.checked })} />
              Buys from us
            </label>
          </div>
        </Field>

        {error ? <div className="sm:col-span-2"><Alert>{error}</Alert></div> : null}
        <div className="flex gap-2 sm:col-span-2">
          <Button type="submit" variant="primary" loading={busy} disabled={f.name.length < 2}>
            Add
          </Button>
          <Button type="button" onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
