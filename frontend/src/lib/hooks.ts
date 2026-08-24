"use client";

import * as React from "react";

import { ApiError } from "./api";

interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/**
 * Fetch-on-mount with a stable refetch. Deliberately not a data library — the app has a
 * handful of screens and no cross-screen cache invalidation to speak of.
 *
 * State is only ever set from the promise callbacks, never synchronously in the effect body.
 * That keeps it clear of React 19's cascading-render rule, and it gives better behaviour when
 * filters change: the previous results stay on screen until the new ones arrive, instead of
 * flashing an empty table on every keystroke.
 */
export function useAsync<T>(
  loader: () => Promise<T>,
  deps: React.DependencyList,
): AsyncState<T> & { reload: () => void } {
  const [state, setState] = React.useState<AsyncState<T>>({
    data: null,
    error: null,
    loading: true,
  });
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;

    loader()
      .then((result) => {
        if (!cancelled) setState({ data: result, error: null, loading: false });
      })
      .catch((err) => {
        if (cancelled) return;
        // A 401 already redirected; surfacing it would flash an error on the way out.
        if (err instanceof ApiError && err.status === 401) {
          setState((s) => ({ ...s, loading: false }));
          return;
        }
        setState({
          data: null,
          error: err instanceof ApiError ? err.message : "Could not load this.",
          loading: false,
        });
      });

    return () => {
      cancelled = true;
    };
    // `loader` is recreated on every render by design; `deps` is what actually identifies
    // the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = React.useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    setNonce((n) => n + 1);
  }, []);

  return { ...state, reload };
}

/** Debounces a value — used so typing in the directory search does not fire a request per key. */
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = React.useState(value);

  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
