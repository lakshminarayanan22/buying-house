"use client";

import * as React from "react";

import { AppShell, PageHeader } from "@/components/AppShell";
import { Avatar } from "@/components/Avatar";
import { Alert, Badge, Button, Card, CardHeader, Field, Input } from "@/components/ui";
import { ApiError, api, setToken } from "@/lib/api";
import { titleCase } from "@/lib/format";
import { useRequireSession, useSession } from "@/lib/session";

export default function AccountPage() {
  const { user, loading } = useRequireSession();
  if (loading || !user) return null;

  return (
    <AppShell>
      <PageHeader title="Your account" />
      <div className="grid max-w-3xl gap-5">
        <Card>
          <div className="flex items-center gap-4 px-5 py-4">
            <Avatar name={user.name} url={user.avatar_url} size={44} />
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-base font-semibold">
                {user.name}
                <Badge tone="sky">{titleCase(user.role)}</Badge>
              </div>
              <div className="readout text-xs" style={{ color: "var(--text-muted)" }}>
                {user.email}
              </div>
              <div className="mt-1 text-[11px]" style={{ color: "var(--text-subtle)" }}>
                {user.google_linked ? "Signs in with Google" : "Not yet linked to a Google account"}
                {user.has_password ? " · password added" : ""}
              </div>
            </div>
          </div>
        </Card>

        <PasswordCard hasPassword={user.has_password} />
      </div>
    </AppShell>
  );
}

function PasswordCard({ hasPassword }: { hasPassword: boolean }) {
  const { refresh } = useSession();
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  return (
    <Card>
      <CardHeader
        title={hasPassword ? "Change your password" : "Add a password"}
        subtitle="Optional. A second way in if Google is ever unavailable — your Google sign-in keeps working either way."
      />
      <form
        className="space-y-3 px-5 py-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (next !== confirm) {
            setError("The two new passwords don't match.");
            return;
          }
          setBusy(true);
          setError(null);
          setDone(false);
          void (async () => {
            try {
              const session = await api.post<{ access_token: string }>("/auth/password", {
                current_password: hasPassword ? current : null,
                new_password: next,
              });
              // Changing a password signs out every other session; this one gets a new token.
              setToken(session.access_token);
              await refresh();
              setCurrent(""); setNext(""); setConfirm("");
              setDone(true);
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "That didn't work.");
            } finally {
              setBusy(false);
            }
          })();
        }}
      >
        {error ? <Alert>{error}</Alert> : null}
        {done ? (
          <Alert tone="emerald">
            Saved. Any other device signed in to your account has been signed out.
          </Alert>
        ) : null}

        {hasPassword ? (
          <Field label="Current password">
            <Input type="password" autoComplete="current-password" value={current}
                   onChange={(e) => setCurrent(e.target.value)} required />
          </Field>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="New password" hint="At least 10 characters">
            <Input type="password" autoComplete="new-password" value={next}
                   onChange={(e) => setNext(e.target.value)} required minLength={10} />
          </Field>
          <Field label="Repeat it">
            <Input type="password" autoComplete="new-password" value={confirm}
                   onChange={(e) => setConfirm(e.target.value)} required minLength={10} />
          </Field>
        </div>
        <Button type="submit" variant="primary" loading={busy}>
          {hasPassword ? "Change password" : "Add password"}
        </Button>
      </form>
    </Card>
  );
}
