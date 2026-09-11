"use client";

import * as React from "react";

import { Button, Field, Input } from "@/components/ui";
import type { AuthConfig } from "@/lib/types";

/* Just the corner of Google Identity Services this uses. Typed here rather than pulling in a
   types package for three functions. */
interface GoogleIdApi {
  initialize(config: {
    client_id: string;
    callback: (response: { credential: string }) => void;
    hd?: string;
    ux_mode?: "popup" | "redirect";
    auto_select?: boolean;
    cancel_on_tap_outside?: boolean;
  }): void;
  renderButton(parent: HTMLElement, options: Record<string, string | number>): void;
}

declare global {
  interface Window {
    google?: { accounts: { id: GoogleIdApi } };
  }
}

const GIS_SRC = "https://accounts.google.com/gsi/client";
let gisLoading: Promise<void> | null = null;

/** Load Google's script once per page, however many buttons ask for it. */
function loadGis(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  gisLoading ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = GIS_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      gisLoading = null;          // let a later attempt retry rather than cache the failure
      reject(new Error("Could not load Google sign-in"));
    };
    document.head.appendChild(script);
  });
  return gisLoading;
}

function prefersDark(): boolean {
  const forced = document.documentElement.getAttribute("data-appearance");
  if (forced) return forced === "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/**
 * The Google button — or, when the backend runs the development stub, a form standing in for
 * it. Either way the result is a credential handed to `onCredential`.
 *
 * It is Google's own rendered button, not a lookalike: their brand rules require it, and it
 * brings the account chooser with it. `hd` asks Google to offer only accounts from our
 * Workspace; that is a convenience for the person choosing, and the server enforces the same
 * rule regardless.
 */
export function GoogleSignIn({
  config,
  onCredential,
  text = "signin_with",
  busy = false,
}: {
  config: AuthConfig;
  onCredential: (credential: string) => void;
  text?: "signin_with" | "continue_with";
  busy?: boolean;
}) {
  const slot = React.useRef<HTMLDivElement>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  // Google's callback is registered once at initialize(); route it through a ref so it always
  // reaches the latest handler without re-initialising the button.
  const handler = React.useRef(onCredential);
  React.useEffect(() => {
    handler.current = onCredential;
  }, [onCredential]);

  const clientId = config.google_backend === "google" ? config.google_client_id : null;

  React.useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    loadGis()
      .then(() => {
        const gis = window.google?.accounts.id;
        if (cancelled || !gis || !slot.current) return;
        gis.initialize({
          client_id: clientId,
          callback: (response) => handler.current(response.credential),
          hd: config.allowed_domain,
          ux_mode: "popup",
          auto_select: false,
          cancel_on_tap_outside: true,
        });
        gis.renderButton(slot.current, {
          type: "standard",
          theme: prefersDark() ? "filled_black" : "outline",
          size: "large",
          text,
          shape: "rectangular",
          logo_alignment: "left",
          width: Math.min(slot.current.clientWidth || 320, 400),
        });
      })
      .catch((err: Error) => {
        if (!cancelled) setLoadError(`${err.message}. Check your connection and reload.`);
      });
    return () => {
      cancelled = true;
    };
  }, [clientId, config.allowed_domain, text]);

  if (config.google_backend === "stub") {
    return <StubSignIn domain={config.allowed_domain} busy={busy} onCredential={onCredential} />;
  }

  return (
    <div>
      {/* Fixed height so the card doesn't jump when Google's iframe arrives. */}
      <div ref={slot} className="flex min-h-[44px] w-full justify-center" aria-busy={busy} />
      {loadError ? (
        <p className="mt-2 text-center text-xs" style={{ color: "var(--danger)" }}>{loadError}</p>
      ) : null}
    </div>
  );
}

/**
 * Test-mode stand-in for the Google button: one box, your Ecolink email.
 *
 * It used to ask for "Google account" and "Name on the account", and people couldn't tell what
 * either was for. The name was never needed — real Google supplies it, and here it is read off
 * the address (priya.raman@ → Priya Raman) — so it went, leaving a single field whose label
 * says exactly what to type.
 */
function StubSignIn({
  domain,
  busy,
  onCredential,
}: {
  domain: string;
  busy: boolean;
  onCredential: (credential: string) => void;
}) {
  const [email, setEmail] = React.useState("");
  const typed = email.trim().toLowerCase();
  const after = typed.includes("@") ? typed.slice(typed.indexOf("@") + 1) : "";
  // Only once they've typed past the @, and only once what follows can no longer become our
  // domain — so "lakshmi@ecol" doesn't nag mid-word, but "lakshmi@gmail" does.
  const wrongDomain = after.length > 0 && !domain.startsWith(after);

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        onCredential(`stub:${typed}`);
      }}
    >
      <Field
        label="Your Ecolink email address"
        hint={wrongDomain ? undefined : `The one ending in @${domain}`}
        error={wrongDomain ? `That isn't an @${domain} address — only Ecolink emails can sign in.` : null}
      >
        <Input
          type="email"
          autoComplete="email"
          autoFocus
          placeholder={`yourname@${domain}`}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
      </Field>
      <Button type="submit" variant="primary" loading={busy} disabled={wrongDomain} className="w-full">
        Sign in
      </Button>
      <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-subtle)" }}>
        <span className="font-medium" style={{ color: "var(--warning)" }}>Test mode.</span>{" "}
        Google sign-in isn&apos;t connected yet, so for now you just type your email. Once it is,
        this box becomes the usual &ldquo;Sign in with Google&rdquo; button.
      </p>
    </form>
  );
}
