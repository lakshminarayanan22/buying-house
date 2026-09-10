"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { AppShell, PageHeader } from "@/components/AppShell";
import { Avatar } from "@/components/Avatar";
import {
  Alert, Badge, Button, Card, CardHeader, EmptyState, Select, Table, Td, Th,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { since, titleCase } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import { useRequireSession } from "@/lib/session";
import { TEAM_CHANGED } from "@/lib/team";
import type { TeamMember, UserRole } from "@/lib/types";

export default function TeamPage() {
  const { user, loading } = useRequireSession();
  const router = useRouter();
  const team = useAsync(() => api.get<TeamMember[]>("/users"), []);
  const [error, setError] = React.useState<string | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);

  // The server refuses non-admins anyway; this just avoids showing them a page of errors.
  React.useEffect(() => {
    if (user && user.role !== "ADMIN") router.replace("/");
  }, [user, router]);

  if (loading || !user || user.role !== "ADMIN") return null;

  const act = async (id: string, request: () => Promise<unknown>) => {
    setBusyId(id);
    setError(null);
    try {
      await request();
      team.reload();
      window.dispatchEvent(new Event(TEAM_CHANGED));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work.");
    } finally {
      setBusyId(null);
    }
  };

  const rows = team.data ?? [];
  const pending = rows.filter((r) => r.status === "PENDING");
  const active = rows.filter((r) => r.status === "ACTIVE");
  const closed = rows.filter((r) => r.status === "REJECTED" || r.status === "DISABLED");

  return (
    <AppShell>
      <PageHeader
        title="Team"
        subtitle="Who can use Ecolink, and anyone waiting for you to let them in."
      />

      {error ? <div className="mb-4"><Alert>{error}</Alert></div> : null}
      {team.error ? <div className="mb-4"><Alert>{team.error}</Alert></div> : null}

      <div className="space-y-5">
        <Card rail>
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                Waiting for approval
                {pending.length ? <Badge tone="amber" lamp live>{pending.length}</Badge> : null}
              </span>
            }
            subtitle="They've signed in with a verified Ecolink Google account. Approving is one-time."
          />
          {team.loading && !team.data ? (
            <EmptyState title="Loading…" />
          ) : pending.length === 0 ? (
            <EmptyState title="Nobody is waiting" hint="New requests appear here, and every admin gets an email." />
          ) : (
            <ul>
              {pending.map((p) => (
                <PendingRow
                  key={p.id}
                  person={p}
                  busy={busyId === p.id}
                  onApprove={(role) => act(p.id, () => api.post(`/users/${p.id}/approve`, { role }))}
                  onReject={() => act(p.id, () => api.post(`/users/${p.id}/reject`))}
                />
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader
            title="People with access"
            subtitle="Switching someone off ends every session they have open and blocks both Google and password sign-in."
          />
          {active.length === 0 ? (
            <EmptyState title="Nobody yet" />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Person</Th><Th>Role</Th><Th>Signs in with</Th><Th>Last sign-in</Th>
                  <Th>Approved by</Th><Th />
                </tr>
              </thead>
              <tbody>
                {active.map((p) => {
                  const self = p.id === user.id;
                  return (
                    <tr key={p.id}>
                      <Td><Person person={p} self={self} /></Td>
                      <Td>
                        <Select
                          value={p.role}
                          disabled={self || busyId === p.id}
                          title={self ? "You can't change your own role" : undefined}
                          onChange={(e) => {
                            const role = e.target.value as UserRole;
                            void act(p.id, () => api.put(`/users/${p.id}/role`, { role }));
                          }}
                          className="w-32 px-1.5 py-1 text-xs"
                        >
                          <option value="MEMBER">Member</option>
                          <option value="ADMIN">Admin</option>
                        </Select>
                      </Td>
                      <Td>
                        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                          {signInMethods(p)}
                        </span>
                      </Td>
                      <Td readout={false}>
                        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                          {since(p.last_login_at)}
                        </span>
                      </Td>
                      <Td>
                        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                          {p.reviewed_by_name ?? (p.reviewed_at ? "Configuration" : "—")}
                        </span>
                      </Td>
                      <Td align="right" readout={false}>
                        {self ? null : (
                          <Button
                            size="sm"
                            variant="ghost"
                            loading={busyId === p.id}
                            onClick={() => {
                              if (window.confirm(`Switch off ${p.name}'s access? They'll be signed out everywhere, straight away.`)) {
                                void act(p.id, () => api.post(`/users/${p.id}/disable`));
                              }
                            }}
                          >
                            Switch off
                          </Button>
                        )}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </Card>

        {closed.length ? (
          <Card>
            <CardHeader title="Declined and switched off" subtitle="Nothing is deleted — you can let anyone here back in." />
            <Table>
              <tbody>
                {closed.map((p) => (
                  <tr key={p.id}>
                    <Td><Person person={p} /></Td>
                    <Td>
                      <Badge tone={p.status === "REJECTED" ? "rose" : "slate"} lamp>
                        {p.status === "REJECTED" ? "Declined" : "Switched off"}
                      </Badge>
                    </Td>
                    <Td readout={false}>
                      <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                        {p.reviewed_by_name ? `by ${p.reviewed_by_name}, ` : ""}{since(p.reviewed_at)}
                      </span>
                    </Td>
                    <Td align="right" readout={false}>
                      <Button
                        size="sm"
                        loading={busyId === p.id}
                        onClick={() => act(p.id, () =>
                          p.status === "REJECTED"
                            ? api.post(`/users/${p.id}/approve`, { role: "MEMBER" })
                            : api.post(`/users/${p.id}/restore`))}
                      >
                        {p.status === "REJECTED" ? "Approve as Member" : "Restore access"}
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        ) : null}
      </div>
    </AppShell>
  );
}

function PendingRow({
  person,
  busy,
  onApprove,
  onReject,
}: {
  person: TeamMember;
  busy: boolean;
  onApprove: (role: UserRole) => void;
  onReject: () => void;
}) {
  const [role, setRole] = React.useState<UserRole>("MEMBER");
  return (
    <li
      className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3 last:border-b-0"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="flex items-center gap-3">
        <Person person={person} />
        <span className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
          asked {since(person.created_at)}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Select value={role} onChange={(e) => setRole(e.target.value as UserRole)}
                className="w-32 px-1.5 py-1 text-xs" aria-label="Role to approve as">
          <option value="MEMBER">as Member</option>
          <option value="ADMIN">as Admin</option>
        </Select>
        <Button size="sm" variant="primary" loading={busy} onClick={() => onApprove(role)}>
          Approve
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onReject}>
          Decline
        </Button>
      </div>
    </li>
  );
}

function Person({ person, self = false }: { person: TeamMember; self?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <Avatar name={person.name} url={person.avatar_url} />
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 text-sm font-medium">
          {person.name}
          {self ? <Badge>You</Badge> : null}
          {person.role === "ADMIN" && person.status === "ACTIVE" ? (
            <Badge tone="sky">{titleCase(person.role)}</Badge>
          ) : null}
        </div>
        <div className="readout text-[11px]" style={{ color: "var(--text-subtle)" }}>
          {person.email}
        </div>
      </div>
    </div>
  );
}

function signInMethods(p: TeamMember): string {
  if (p.google_linked && p.has_password) return "Google + password";
  if (p.google_linked) return "Google";
  // Only accounts from before Google sign-in existed (the demo seed). Signing in with Google
  // once links them.
  return p.has_password ? "Password only" : "—";
}
