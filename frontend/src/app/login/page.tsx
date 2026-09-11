"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ApiError, api, googleSignIn, login } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { AuthConfig, SignInResult } from "@/lib/types";
import { Alert, Button, Card, Field, Input, Lamp, Spinner } from "@/components/ui";
import { BrandMark } from "@/components/BrandMark";
import { GoogleSignIn } from "@/components/GoogleSignIn";

function LoginScreen() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useSession();

  const [config, setConfig] = React.useState<AuthConfig | null>(null);
  const [configError, setConfigError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<SignInResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    api.get<AuthConfig>("/auth/config")
      .then(setConfig)
      .catch(() => setConfigError("Can't reach the Ecolink server. Is it running?"));
  }, []);

  const enter = React.useCallback(async () => {
    await refresh();
    router.replace(params.get("next") || "/");
  }, [refresh, router, params]);

  const onCredential = React.useCallback(
    (credential: string) => {
      setBusy(true);
      setError(null);
      void (async () => {
        try {
          const outcome = await googleSignIn(credential);
          if (outcome.status === "ACTIVE") {
            await enter();
            return;
          }
          setResult(outcome);
        } catch (err) {
          setError(err instanceof ApiError ? err.message : "Sign-in failed. Try again.");
        } finally {
          setBusy(false);
        }
      })();
    },
    [enter],
  );

  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2">
          <div className="flex items-center gap-2.5">
            <BrandMark size={30} />
            <h1 className="text-lg font-semibold" style={{ letterSpacing: "0.16em" }}>
              ECOLINK
            </h1>
          </div>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            Deals, companies and commission
          </p>
        </div>

        <Card rail className="p-5">
          {configError ? (
            <Alert>{configError}</Alert>
          ) : !config ? (
            <div className="flex justify-center py-6" style={{ color: "var(--text-subtle)" }}>
              <Spinner />
            </div>
          ) : result ? (
            <StatusScreen
              result={result}
              config={config}
              busy={busy}
              error={error}
              onCredential={onCredential}
              onBack={() => {
                setResult(null);
                setError(null);
              }}
            />
          ) : (
            <SignIn
              config={config}
              busy={busy}
              error={error}
              onCredential={onCredential}
              onPasswordSignedIn={enter}
            />
          )}
        </Card>
      </div>
    </main>
  );
}

function SignIn({
  config,
  busy,
  error,
  onCredential,
  onPasswordSignedIn,
}: {
  config: AuthConfig;
  busy: boolean;
  error: string | null;
  onCredential: (credential: string) => void;
  onPasswordSignedIn: () => Promise<void>;
}) {
  const [withPassword, setWithPassword] = React.useState(false);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold">Sign in to Ecolink</h2>
        <p className="mt-1 text-xs leading-relaxed" style={{ color: "var(--text-muted)" }}>
          Use your <span className="readout">@{config.allowed_domain}</span> email.
        </p>
        <p className="mt-1 text-xs leading-relaxed" style={{ color: "var(--text-subtle)" }}>
          First time here? You&apos;ll be asked to wait while an admin approves you. That only
          happens once.
        </p>
      </div>

      {error ? <Alert>{error}</Alert> : null}

      {/* One way in on screen at a time. Showing both put two email boxes and two "Sign in"
          buttons on the same card, and nobody could tell which one to use. */}
      {withPassword ? null : (
        <GoogleSignIn config={config} busy={busy} onCredential={onCredential} />
      )}

      {config.password_login ? (
        withPassword ? (
          <PasswordForm onSignedIn={onPasswordSignedIn} onCancel={() => setWithPassword(false)} />
        ) : (
          <div className="flex items-center gap-3 pt-1">
            <span className="h-px flex-1" style={{ background: "var(--border)" }} />
            <button
              type="button"
              onClick={() => setWithPassword(true)}
              className="text-xs hover:underline"
              style={{ color: "var(--text-muted)" }}
            >
              Sign in with a password instead
            </button>
            <span className="h-px flex-1" style={{ background: "var(--border)" }} />
          </div>
        )
      ) : null}
    </div>
  );
}

/** For approved accounts that have added a password on their Account page. */
function PasswordForm({
  onSignedIn,
  onCancel,
}: {
  onSignedIn: () => Promise<void>;
  onCancel: () => void;
}) {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        void (async () => {
          try {
            await login(email, password);
            await onSignedIn();
          } catch (err) {
            setError(err instanceof ApiError ? err.message : "Something went wrong.");
            setBusy(false);
          }
        })();
      }}
    >
      {error ? <Alert>{error}</Alert> : null}
      <Field label="Your Ecolink email address">
        <Input type="email" autoComplete="username" value={email}
               onChange={(e) => setEmail(e.target.value)} required />
      </Field>
      <Field label="Password">
        <Input type="password" autoComplete="current-password" value={password}
               onChange={(e) => setPassword(e.target.value)} required />
      </Field>
      <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-subtle)" }}>
        Only if you&apos;ve already added a password from <em>Your account</em>. Signing in for
        the first time? Go back and use your email instead.
      </p>
      <div className="flex gap-2">
        <Button type="submit" variant="primary" loading={busy} className="flex-1">
          Sign in with password
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>Back</Button>
      </div>
    </form>
  );
}

const SCREENS = {
  PENDING: { tone: "amber", live: true, title: "Waiting for approval" },
  REJECTED: { tone: "rose", live: false, title: "Request declined" },
  DISABLED: { tone: "slate", live: false, title: "Access switched off" },
} as const;

function StatusScreen({
  result,
  config,
  busy,
  error,
  onCredential,
  onBack,
}: {
  result: SignInResult;
  config: AuthConfig;
  busy: boolean;
  error: string | null;
  onCredential: (credential: string) => void;
  onBack: () => void;
}) {
  const screen = SCREENS[result.status as keyof typeof SCREENS];
  if (!screen) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Lamp tone={screen.tone} live={screen.live} />
        <h2 className="text-sm font-semibold">{screen.title}</h2>
      </div>

      <div className="rounded-md border px-3 py-2" style={{ borderColor: "var(--border)" }}>
        <div className="text-sm font-medium">{result.name}</div>
        <div className="readout text-xs" style={{ color: "var(--text-muted)" }}>
          {result.email}
        </div>
      </div>

      <p className="text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
        {result.message}
      </p>

      {result.status === "PENDING" ? (
        <ol className="space-y-1.5 text-xs" style={{ color: "var(--text-muted)" }}>
          <Step n={1} done>
            {result.newly_requested ? "Request sent — the admins have been emailed." : "Request received."}
          </Step>
          <Step n={2}>An admin approves you. You&apos;ll get an email when they do.</Step>
          <Step n={3}>Sign in with Google again. From then on you go straight in.</Step>
        </ol>
      ) : null}

      {error ? <Alert>{error}</Alert> : null}

      {result.status === "PENDING" ? (
        <div className="space-y-2 border-t pt-4" style={{ borderColor: "var(--border)" }}>
          <p className="micro text-center">Approved already?</p>
          <GoogleSignIn config={config} busy={busy} onCredential={onCredential}
                        text="continue_with" />
        </div>
      ) : null}

      <Button variant="ghost" size="sm" className="w-full" onClick={onBack}>
        Use a different account
      </Button>
    </div>
  );
}

function Step({ n, done = false, children }: { n: number; done?: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <span
        className="readout mt-px grid h-4 w-4 shrink-0 place-items-center rounded-full text-[10px]"
        style={{
          background: done ? "var(--success-soft)" : "var(--surface-2)",
          color: done ? "var(--success)" : "var(--text-subtle)",
          boxShadow: "0 0 0 1px var(--border)",
        }}
      >
        {done ? "✓" : n}
      </span>
      <span>{children}</span>
    </li>
  );
}

export default function LoginPage() {
  return (
    <React.Suspense fallback={null}>
      <LoginScreen />
    </React.Suspense>
  );
}
