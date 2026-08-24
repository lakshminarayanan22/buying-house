"use client";

import * as React from "react";
import Link from "next/link";

import { api } from "@/lib/api";
import { useAsync, useDebounced } from "@/lib/hooks";
import { PageHeader } from "@/components/AppShell";
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
  cx,
} from "@/components/ui";
import { statusTone, titleCase } from "@/lib/format";
import type { DirectorySupplier, FacetValue, Page } from "@/lib/types";

type Facets = Record<"process" | "category" | "certification", FacetValue[]>;

/**
 * The supplier directory.
 *
 * Every filter here is a deterministic predicate over structured data — the same hard filters
 * the matching engine will run before it scores anything. If this screen cannot find the right
 * factory today, no model will fix that later, so it is worth getting right first.
 */
export default function SupplierDirectory() {
  const [search, setSearch] = React.useState("");
  const [processes, setProcesses] = React.useState<string[]>([]);
  const [categories, setCategories] = React.useState<string[]>([]);
  const [certifications, setCertifications] = React.useState<string[]>([]);
  const [maxMoq, setMaxMoq] = React.useState("");
  const [moqUom, setMoqUom] = React.useState("PCS");
  const [gsm, setGsm] = React.useState("");
  const [includeUnverified, setIncludeUnverified] = React.useState(true);

  const debouncedSearch = useDebounced(search);
  const debouncedMoq = useDebounced(maxMoq, 400);
  const debouncedGsm = useDebounced(gsm, 400);

  const facets = useAsync(() => api.get<Facets>("/directory/facets"), []);

  const results = useAsync(
    () =>
      api.get<Page<DirectorySupplier>>("/directory/suppliers", {
        search: debouncedSearch,
        process: processes,
        category: categories,
        certification: certifications,
        // An MOQ without its unit is meaningless — a 500 kg minimum does not satisfy a
        // 1,000-piece order — so the unit always travels with the number.
        max_moq: debouncedMoq || undefined,
        moq_uom: debouncedMoq ? moqUom : undefined,
        gsm: debouncedGsm || undefined,
        include_unverified: includeUnverified,
        page_size: 50,
      }),
    [
      debouncedSearch,
      processes.join(","),
      categories.join(","),
      certifications.join(","),
      debouncedMoq,
      moqUom,
      debouncedGsm,
      includeUnverified,
    ],
  );

  const activeFilters =
    processes.length + categories.length + certifications.length + (maxMoq ? 1 : 0) + (gsm ? 1 : 0);

  function clearAll() {
    setProcesses([]);
    setCategories([]);
    setCertifications([]);
    setMaxMoq("");
    setGsm("");
    setSearch("");
  }

  return (
    <>
      <PageHeader
        title="Supplier directory"
        subtitle={
          results.data
            ? `${results.data.total} supplier${results.data.total === 1 ? "" : "s"} match`
            : "Loading…"
        }
        actions={
          <>
            <a
              href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"}/imports/suppliers/template`}
            >
              <Button size="sm">Excel template</Button>
            </a>
            <Link href="/internal/suppliers/new">
              <Button size="sm" variant="primary">
                Register a supplier
              </Button>
            </Link>
          </>
        }
      />

      <div className="grid gap-5 lg:grid-cols-[260px_1fr]">
        <aside className="space-y-4">
          <Card className="p-4">
            <Field label="Search">
              <Input
                placeholder="Name or city"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </Field>

            <div className="mt-3 grid grid-cols-2 gap-2">
              <Field label="Max MOQ">
                <Input
                  inputMode="numeric"
                  placeholder="1000"
                  value={maxMoq}
                  onChange={(e) => setMaxMoq(e.target.value.replace(/[^\d.]/g, ""))}
                />
              </Field>
              <Field label="Unit">
                <Select value={moqUom} onChange={(e) => setMoqUom(e.target.value)}>
                  {["PCS", "KG", "METRES", "YARDS", "DOZENS"].map((u) => (
                    <option key={u} value={u}>
                      {u}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>

            <div className="mt-3">
              <Field label="GSM" hint="Matches suppliers whose range covers this">
                <Input
                  inputMode="numeric"
                  placeholder="180"
                  value={gsm}
                  onChange={(e) => setGsm(e.target.value.replace(/\D/g, ""))}
                />
              </Field>
            </div>

            <label className="mt-3 flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
              <input
                type="checkbox"
                checked={includeUnverified}
                onChange={(e) => setIncludeUnverified(e.target.checked)}
              />
              Include unverified
            </label>

            {activeFilters > 0 ? (
              <Button size="sm" variant="ghost" className="mt-3 w-full" onClick={clearAll}>
                Clear {activeFilters} filter{activeFilters === 1 ? "" : "s"}
              </Button>
            ) : null}
          </Card>

          <FacetGroup
            title="Process"
            values={facets.data?.process ?? []}
            selected={processes}
            onChange={setProcesses}
          />
          <FacetGroup
            title="Product category"
            values={facets.data?.category ?? []}
            selected={categories}
            onChange={setCategories}
          />
          <FacetGroup
            title="Certification"
            values={facets.data?.certification ?? []}
            selected={certifications}
            onChange={setCertifications}
            emptyHint="No verified certificates on file yet. A claimed certificate does not count until it is checked."
          />
        </aside>

        <Card>
          <CardHeader
            title="Results"
            subtitle="Capacity, MOQ and certificate validity are filtered in the database, not in the browser"
          />
          {results.error ? (
            <div className="p-4">
              <Alert>{results.error}</Alert>
            </div>
          ) : results.loading ? (
            <EmptyState title="Loading…" />
          ) : (results.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              title="No suppliers match these filters"
              hint="Try removing a filter, or register the factory you are looking for."
            />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Supplier</Th>
                  <Th>Processes</Th>
                  <Th>Categories</Th>
                  <Th>Certifications</Th>
                  <Th>Status</Th>
                  <Th>Profile</Th>
                </tr>
              </thead>
              <tbody>
                {results.data?.items.map((supplier) => (
                  <tr key={supplier.id}>
                    <Td>
                      {supplier.is_identity_visible ? (
                        <Link
                          href={`/internal/suppliers/${supplier.id}`}
                          className="font-medium hover:underline"
                        >
                          {supplier.trade_name || supplier.legal_name}
                        </Link>
                      ) : (
                        // A brand sees the capabilities and a stable handle, never the name,
                        // until an identity reveal is granted.
                        <span className="font-mono text-xs" title="Identity withheld until revealed">
                          {supplier.masked_ref}
                        </span>
                      )}
                      <div className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                        {[supplier.city, supplier.state].filter(Boolean).join(", ") || "—"}
                      </div>
                    </Td>
                    <Td>
                      <ChipList values={supplier.processes} />
                    </Td>
                    <Td>
                      <ChipList values={supplier.categories} />
                    </Td>
                    <Td>
                      {supplier.certifications.length ? (
                        <ChipList values={supplier.certifications} tone="emerald" />
                      ) : (
                        <span style={{ color: "var(--text-subtle)" }}>—</span>
                      )}
                    </Td>
                    <Td>
                      <Badge tone={statusTone(supplier.status)}>{titleCase(supplier.status)}</Badge>
                    </Td>
                    <Td>
                      <CompletenessBar value={supplier.completeness_pct} />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}

function ChipList({ values, tone = "slate" }: { values: string[]; tone?: string }) {
  const shown = values.slice(0, 3);
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((value) => (
        <Badge key={value} tone={tone}>
          {value}
        </Badge>
      ))}
      {values.length > shown.length ? (
        <Badge title={values.slice(3).join(", ")}>+{values.length - shown.length}</Badge>
      ) : null}
      {values.length === 0 ? <span style={{ color: "var(--text-subtle)" }}>—</span> : null}
    </div>
  );
}

function FacetGroup({
  title,
  values,
  selected,
  onChange,
  emptyHint,
}: {
  title: string;
  values: FacetValue[];
  selected: string[];
  onChange: (next: string[]) => void;
  emptyHint?: string;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const shown = expanded ? values : values.slice(0, 6);

  function toggle(code: string) {
    onChange(selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code]);
  }

  return (
    <Card>
      <div className="border-b px-4 py-2.5" style={{ borderColor: "var(--border)" }}>
        <h3 className="text-[11px] font-semibold tracking-wide uppercase" style={{ color: "var(--text-subtle)" }}>
          {title}
        </h3>
      </div>
      {values.length === 0 ? (
        <p className="px-4 py-3 text-xs" style={{ color: "var(--text-subtle)" }}>
          {emptyHint ?? "Nothing here yet."}
        </p>
      ) : (
        <>
          <ul className="px-2 py-1.5">
            {shown.map((value) => {
              const active = selected.includes(value.code);
              return (
                <li key={value.code}>
                  <button
                    type="button"
                    onClick={() => toggle(value.code)}
                    className={cx(
                      "flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-xs",
                    )}
                    style={{
                      background: active ? "var(--accent-soft)" : "transparent",
                      color: active ? "var(--accent)" : "var(--text)",
                      fontWeight: active ? 600 : 400,
                    }}
                  >
                    <span className="truncate">{value.name}</span>
                    <span className="tabular shrink-0" style={{ color: "var(--text-subtle)" }}>
                      {value.count}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {values.length > 6 ? (
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className="w-full border-t px-4 py-1.5 text-left text-[11px]"
              style={{ borderColor: "var(--border)", color: "var(--accent)" }}
            >
              {expanded ? "Show fewer" : `Show all ${values.length}`}
            </button>
          ) : null}
        </>
      )}
    </Card>
  );
}
