"use client";

/**
 * Session context.
 *
 * The server is the authority on what a user may see — `portals` comes from /auth/me rather
 * than being inferred from the role string in the browser. Route guarding here is a UX
 * courtesy; every endpoint enforces the same rules again server-side, because a hidden nav
 * link is not access control.
 */
import * as React from "react";
import { useRouter, usePathname } from "next/navigation";

import { api, getToken, logout as apiLogout } from "./api";
import type { CurrentUser } from "./types";
import { translate, type Language } from "./i18n";

interface SessionState {
  user: CurrentUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
  t: (key: string) => string;
}

const SessionContext = React.createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<CurrentUser | null>(null);
  const [loading, setLoading] = React.useState(true);
  const router = useRouter();

  const refresh = React.useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await api.get<CurrentUser>("/auth/me"));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    // Synchronising React with two external systems — the token in localStorage and the
    // server's view of who that token belongs to — which is exactly what an effect is for.
    // The no-token branch resolves without awaiting, hence the narrow disable.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const signOut = React.useCallback(async () => {
    await apiLogout();
    setUser(null);
    router.push("/login");
  }, [router]);

  const t = React.useCallback(
    (key: string) => translate(key, (user?.language_pref ?? "en") as Language),
    [user?.language_pref],
  );

  return (
    <SessionContext.Provider value={{ user, loading, refresh, signOut, t }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const context = React.useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside a SessionProvider");
  return context;
}

/** The landing route for a user, derived from the portal the server granted them. */
export function homePathFor(user: CurrentUser | null): string {
  if (!user) return "/login";
  if (user.portals.includes("internal")) return "/internal";
  if (user.portals.includes("supplier")) return "/supplier";
  if (user.portals.includes("brand")) return "/brand";
  return "/login";
}

/** Redirects to the login screen, or away from a portal the user has no claim to. */
export function useRequirePortal(portal: "internal" | "brand" | "supplier") {
  const { user, loading } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  React.useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    if (!user.portals.includes(portal)) router.replace(homePathFor(user));
  }, [loading, user, portal, router, pathname]);

  return { user, loading };
}
