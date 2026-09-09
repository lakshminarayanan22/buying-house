"use client";

import Link from "next/link";

import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { useRequireSession } from "@/lib/session";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Alert, Badge, Card, CardHeader, EmptyState, StatusBadge, Table, Td, Th } from "@/components/ui";
import { daysAgo, formatDate, money, titleCase } from "@/lib/format";
import type { Dashboard } from "@/lib/types";

/**
 * The three questions asked every morning: what is shipping, who owes us money, and what has
 * gone quiet. Nothing else is on this page.
 */
export default function DashboardPage() {
  const { user, loading } = useRequireSession();
  const { data, error } = useAsync(() => api.get<Dashboard>("/dashboard"), []);

  if (loading || !user) return null;

  const outstanding = data?.commission.outstanding ?? 0;
  const overdueShipments = data?.shipping.filter((s) => s.overdue).length ?? 0;

  return (
    <AppShell>
      <PageHeader
        title={`Good to see you, ${user.name.split(" ")[0]}`}
        subtitle="What ships next, who owes us, and what has gone quiet."
      />

      {error ? <Alert>{error}</Alert> : null}

      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Commission owed", value: money(outstanding) },
          { label: "Received", value: money(data?.commission.received ?? 0) },
          { label: "Shipping soon", value: String(data?.shipping.length ?? 0),
            hint: overdueShipments ? `${overdueShipments} overdue` : undefined },
          { label: "Gone quiet", value: String(data?.quiet.length ?? 0) },
        ].map((stat) => (
          <Card key={stat.label} className="px-4 py-3">
            <div className="micro">{stat.label}</div>
            <div className="readout mt-1 text-2xl font-semibold">{stat.value}</div>
            {stat.hint ? (
              <div className="text-[11px]" style={{ color: "var(--danger)" }}>{stat.hint}</div>
            ) : null}
          </Card>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Shipping this week" subtitle="Anything already late is flagged" />
          {(data?.shipping.length ?? 0) === 0 ? (
            <EmptyState title="Nothing due" hint="Legs with a ship date in the next week appear here." />
          ) : (
            <Table>
              <thead>
                <tr><Th>Date</Th><Th>Deal</Th><Th>Company</Th><Th align="right">Value</Th></tr>
              </thead>
              <tbody>
                {data?.shipping.map((row, i) => (
                  <tr key={`${row.deal_no}-${i}`}>
                    <Td>
                      <div>{formatDate(row.ship_date)}</div>
                      <div
                        className="text-[11px]"
                        style={{ color: row.overdue ? "var(--danger)" : "var(--text-subtle)" }}
                      >
                        {row.overdue ? `${-row.days_out}d overdue` : `in ${row.days_out}d`}
                      </div>
                    </Td>
                    <Td>
                      <div className="font-mono text-[11px]" style={{ color: "var(--text-subtle)" }}>
                        {row.deal_no}
                      </div>
                      <div className="truncate">{row.title}</div>
                    </Td>
                    <Td>
                      <div>{row.company}</div>
                      <div className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                        {row.process ?? titleCase(row.role)}
                      </div>
                    </Td>
                    <Td align="right">{money(row.value)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Who owes us commission"
            subtitle="Grouped by who to call, because chasing is a phone call to a company"
          />
          {(data?.commission.by_company.length ?? 0) === 0 ? (
            <EmptyState title="Nothing outstanding" />
          ) : (
            <Table>
              <thead>
                <tr><Th>Company</Th><Th align="right">Amount</Th><Th>Invoiced</Th></tr>
              </thead>
              <tbody>
                {data?.commission.by_company.map((row) => (
                  <tr key={row.company_id}>
                    <Td>
                      <Link href={`/companies/${row.company_id}`} className="font-medium hover:underline">
                        {row.company}
                      </Link>
                      <div className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                        {row.legs} leg{row.legs === 1 ? "" : "s"}
                      </div>
                    </Td>
                    <Td align="right">{money(row.amount)}</Td>
                    <Td>
                      {row.days_outstanding === null ? (
                        <Badge tone="slate">not invoiced</Badge>
                      ) : (
                        <Badge tone={row.days_outstanding > 30 ? "rose" : "amber"}>
                          {row.days_outstanding}d
                        </Badge>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <Card>
          <CardHeader title="Gone quiet" subtitle="Open deals nobody has touched in a fortnight" />
          {(data?.quiet.length ?? 0) === 0 ? (
            <EmptyState title="Everything has been touched recently" />
          ) : (
            <Table>
              <thead>
                <tr><Th>Deal</Th><Th>Status</Th><Th align="right">Last touched</Th></tr>
              </thead>
              <tbody>
                {data?.quiet.map((row) => (
                  <tr key={row.deal_id}>
                    <Td>
                      <Link href={`/deals/${row.deal_id}`} className="font-medium hover:underline">
                        {row.title}
                      </Link>
                      <div className="font-mono text-[11px]" style={{ color: "var(--text-subtle)" }}>
                        {row.deal_no}
                      </div>
                    </Td>
                    <Td><StatusBadge status={row.status} /></Td>
                    <Td align="right" readout={false}>
                      <span style={{ color: row.days_silent > 30 ? "var(--danger)" : undefined }}>
                        {daysAgo(row.days_silent)}
                      </span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <Card>
          <CardHeader title="Follow-ups due" subtitle="Milestones open across every live deal" />
          {(data?.milestones.length ?? 0) === 0 ? (
            <EmptyState title="Nothing due" />
          ) : (
            <Table>
              <thead>
                <tr><Th>Milestone</Th><Th>Deal</Th><Th align="right">Due</Th></tr>
              </thead>
              <tbody>
                {data?.milestones.map((row, i) => (
                  <tr key={`${row.deal_no}-${i}`}>
                    <Td>
                      <div>{row.milestone}</div>
                      <StatusBadge status={row.status} />
                    </Td>
                    <Td>
                      <div className="font-mono text-[11px]" style={{ color: "var(--text-subtle)" }}>
                        {row.deal_no}
                      </div>
                      <div className="truncate">{row.title}</div>
                    </Td>
                    <Td align="right" readout={false}>
                      <span style={{ color: row.overdue ? "var(--danger)" : undefined }}>
                        {formatDate(row.planned_date)}
                      </span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
