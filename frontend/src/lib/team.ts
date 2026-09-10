"use client";

import * as React from "react";

import { api } from "./api";

/** Fired by the Team page after any change, so the header badge recounts immediately. */
export const TEAM_CHANGED = "ecolink-team-changed";

/**
 * How many people are waiting for an admin. Null for members — the endpoint is admin-only
 * and they have nothing to act on.
 *
 * Rechecks on navigation, when the Team page changes something, and once a minute, so a
 * request that arrives while an admin is working shows up without a reload.
 */
export function usePendingCount(isAdmin: boolean, pathname: string): number | null {
  const [count, setCount] = React.useState<number | null>(null);

  React.useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    const load = () =>
      api.get<{ count: number }>("/users/pending-count")
        .then((r) => { if (!cancelled) setCount(r.count); })
        .catch(() => { /* a badge is not worth an error on every screen */ });

    void load();
    const timer = window.setInterval(load, 60_000);
    window.addEventListener(TEAM_CHANGED, load);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener(TEAM_CHANGED, load);
    };
  }, [isAdmin, pathname]);

  return isAdmin ? count : null;
}
