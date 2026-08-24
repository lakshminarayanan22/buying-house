"use client";

import Link from "next/link";

import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/AppShell";
import { Badge, Card, CardHeader, EmptyState, Table, Td, Th, CompletenessBar } from "@/components/ui";
import { formatDate, statusTone, titleCase } from "@/lib/format";
import type { Organization, Page, UnmappedTerm } from "@/lib/types";

export default function InternalDashboard() {
  const { user } = useSession();

  const orgs = useAsync(
    () => api.get<Page<Organization>>("/organizations", { type: "SUPPLIER", page_size: 100 }),
    [],
  );
  const unmapped = useAsync(
    () => api.get<Page<UnmappedTerm>>("/master-data/unmapped", { page_size: 5 }),
    [],
  );

  const items = orgs.data?.items ?? [];
  const byStatus = items.reduce<Record<string, number>>((acc, org) => {
    acc[org.status] = (acc[org.status] ?? 0) + 1;
    return acc;
  }, {});

  // The queue that actually needs a human: submitted profiles waiting on a decision.
  const awaitingReview = items.filter(
    (o) => o.status === "SUBMITTED" || o.status === "UNDER_REVIEW",
  );

  return (
    <>
      <PageHeader
        title={`Good to see you, ${user?.name?.split(" ")[0] ?? ""}`}
        subtitle="Suppliers waiting on you, and the taxonomy terms nobody has mapped yet."
      />

      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Suppliers", value: orgs.data?.total ?? 0, href: "/internal/suppliers" },
          { label: "Verified", value: byStatus.VERIFIED ?? 0, href: "/internal/suppliers" },
          { label: "Awaiting review", value: awaitingReview.length, href: "/internal/suppliers" },
          {
            label: "Unmapped terms",
            value: unmapped.data?.total ?? 0,
            href: "/internal/master-data",
          },
        ].map((stat) => (
          <Link key={stat.label} href={stat.href}>
            <Card className="px-4 py-3 transition-shadow hover:shadow-sm">
              <div className="text-[11px] tracking-wide uppercase" style={{ color: "var(--text-subtle)" }}>
                {stat.label}
              </div>
              <div className="tabular mt-1 text-2xl font-semibold">{stat.value}</div>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Awaiting verification"
            subtitle="Profiles the supplier has submitted and nobody has decided on yet"
          />
          {awaitingReview.length === 0 ? (
            <EmptyState
              title="Nothing waiting"
              hint="Submitted supplier profiles appear here for a sourcing head to verify."
            />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Supplier</Th>
                  <Th>City</Th>
                  <Th>Status</Th>
                  <Th>Submitted</Th>
                </tr>
              </thead>
              <tbody>
                {awaitingReview.map((org) => (
                  <tr key={org.id}>
                    <Td>
                      <Link
                        href={`/internal/suppliers/${org.id}`}
                        className="font-medium hover:underline"
                      >
                        {org.trade_name || org.legal_name}
                      </Link>
                    </Td>
                    <Td>{org.city ?? "—"}</Td>
                    <Td>
                      <Badge tone={statusTone(org.status)}>{titleCase(org.status)}</Badge>
                    </Td>
                    <Td>{formatDate(org.created_at)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Terms nobody has mapped"
            subtitle="Words suppliers typed that the taxonomy does not recognise"
          />
          {(unmapped.data?.items.length ?? 0) === 0 ? (
            <EmptyState title="Taxonomy is clean" hint="Unrecognised terms land here to be mapped." />
          ) : (
            <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
              {unmapped.data?.items.map((term) => (
                <li key={term.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm">{term.raw_text}</div>
                    <div className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                      {titleCase(term.domain)}
                    </div>
                  </div>
                  <Badge tone={term.occurrences > 2 ? "amber" : "slate"}>
                    {term.occurrences}×
                  </Badge>
                </li>
              ))}
            </ul>
          )}
          <div className="border-t px-4 py-2.5" style={{ borderColor: "var(--border)" }}>
            <Link
              href="/internal/master-data"
              className="text-xs hover:underline"
              style={{ color: "var(--accent)" }}
            >
              Open the review queue →
            </Link>
          </div>
        </Card>
      </div>

      <div className="mt-5">
        <Card>
          <CardHeader title="Directory health" subtitle="Profile completeness across all suppliers" />
          {items.length === 0 ? (
            <EmptyState
              title="No suppliers yet"
              hint="Register one, or bulk-import your existing list from Excel."
            />
          ) : (
            <div className="grid gap-x-8 gap-y-2 px-5 py-4 sm:grid-cols-2 lg:grid-cols-3">
              {items.slice(0, 12).map((org) => (
                <SupplierCompleteness key={org.id} org={org} />
              ))}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function SupplierCompleteness({ org }: { org: Organization }) {
  const { data } = useAsync(
    () => api.get<{ completeness_pct: number }>(`/suppliers/${org.id}/completeness`),
    [org.id],
  );
  return (
    <div className="flex items-center justify-between gap-3">
      <Link
        href={`/internal/suppliers/${org.id}`}
        className="truncate text-sm hover:underline"
        title={org.legal_name}
      >
        {org.trade_name || org.legal_name}
      </Link>
      <CompletenessBar value={data?.completeness_pct ?? 0} />
    </div>
  );
}
