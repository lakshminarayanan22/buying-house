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
import { clearStoredConversation } from "./conversation";
import type { Me } from "./types";

interface SessionState {
  user: Me | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

const SessionContext = React.createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<Me | null>(null);
  const [loading, setLoading] = React.useState(true);
  const router = useRouter();

  const refresh = React.useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await api.get<Me>("/auth/me"));
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
    // The Ask thread holds deal values and commissions. It goes with the session, not with the
    // browser — the next person to sign in on this machine must not find it waiting.
    clearStoredConversation();
    router.push("/login");
  }, [router]);


  return (
    <SessionContext.Provider value={{ user, loading, refresh, signOut }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const context = React.useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside a SessionProvider");
  return context;
}


/** Everyone who signs in sees the whole application, so this only guards for a session. */
export function useRequireSession() {
  const { user, loading } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  React.useEffect(() => {
    if (!loading && !user) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [loading, user, router, pathname]);

  return { user, loading };
}
