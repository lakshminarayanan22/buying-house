"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ApiError, login } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Alert, Button, Card, Field, Input } from "@/components/ui";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useSession();

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <h1 className="text-lg font-semibold tracking-tight">Ecolink</h1>
          <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
            Deals, companies and commission
          </p>
        </div>

        <Card className="p-5">
          {error ? (
            <div className="mb-4">
              <Alert>{error}</Alert>
            </div>
          ) : null}

          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              setBusy(true);
              setError(null);
              void (async () => {
                try {
                  await login(email, password);
                  await refresh();
                  router.replace(params.get("next") || "/");
                } catch (err) {
                  setError(err instanceof ApiError ? err.message : "Something went wrong.");
                  setBusy(false);
                }
              })();
            }}
          >
            <Field label="Email">
              <Input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </Field>
            <Field label="Password">
              <Input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>
            <Button type="submit" variant="primary" loading={busy} className="w-full">
              Sign in
            </Button>
          </form>
        </Card>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <React.Suspense fallback={null}>
      <LoginForm />
    </React.Suspense>
  );
}
