"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ApiError, login, requestOtp, verifyOtp } from "@/lib/api";
import { homePathFor, useSession } from "@/lib/session";
import { Alert, Button, Card, Field, Input } from "@/components/ui";

type Mode = "password" | "otp";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useSession();

  // Two doors, deliberately. Internal staff and brands use email and password; a factory owner
  // in Tiruppur uses the phone number we already have and a code over WhatsApp (§5.2).
  const [mode, setMode] = React.useState<Mode>("password");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [phone, setPhone] = React.useState("");
  const [code, setCode] = React.useState("");
  const [codeSent, setCodeSent] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const goHome = async (user: Awaited<ReturnType<typeof login>>) => {
    await refresh();
    router.replace(params.get("next") || homePathFor(user));
  };

  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <h1 className="text-lg font-semibold tracking-tight">Buying House</h1>
          <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
            Sourcing platform for brands and suppliers
          </p>
        </div>

        <Card className="p-5">
          {error ? (
            <div className="mb-4">
              <Alert>{error}</Alert>
            </div>
          ) : null}
          {notice ? (
            <div className="mb-4">
              <Alert tone="sky">{notice}</Alert>
            </div>
          ) : null}

          {mode === "password" ? (
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => goHome(await login(email, password)));
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
          ) : (
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                if (!codeSent) {
                  void run(async () => {
                    const detail = await requestOtp(phone);
                    setCodeSent(true);
                    setNotice(detail);
                  });
                } else {
                  void run(async () => goHome(await verifyOtp(phone, code)));
                }
              }}
            >
              <Field label="Phone number" hint="The number registered with us, with country code">
                <Input
                  type="tel"
                  inputMode="tel"
                  placeholder="+91 90000 00000"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  disabled={codeSent}
                  required
                />
              </Field>
              {codeSent ? (
                <Field label="6-digit code" hint="Sent to your WhatsApp">
                  <Input
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                    required
                  />
                </Field>
              ) : null}
              <Button type="submit" variant="primary" loading={busy} className="w-full">
                {codeSent ? "Sign in" : "Send code"}
              </Button>
              {codeSent ? (
                <button
                  type="button"
                  className="w-full text-center text-xs underline"
                  style={{ color: "var(--text-muted)" }}
                  onClick={() => {
                    setCodeSent(false);
                    setCode("");
                    setNotice(null);
                  }}
                >
                  Use a different number
                </button>
              ) : null}
            </form>
          )}

          <div className="mt-5 border-t pt-4" style={{ borderColor: "var(--border)" }}>
            <button
              type="button"
              className="w-full text-center text-xs underline"
              style={{ color: "var(--text-muted)" }}
              onClick={() => {
                setMode(mode === "password" ? "otp" : "password");
                setError(null);
                setNotice(null);
                setCodeSent(false);
              }}
            >
              {mode === "password"
                ? "Sign in with a code instead"
                : "Sign in with email and password"}
            </button>
          </div>
        </Card>
      </div>
    </main>
  );
}

export default function LoginPage() {
  // useSearchParams needs a Suspense boundary in the App Router.
  return (
    <React.Suspense fallback={null}>
      <LoginForm />
    </React.Suspense>
  );
}
