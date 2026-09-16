"use client";

/**
 * The Ask conversation, held above the pages.
 *
 * Every screen mounts its own <AppShell>, so the dock is unmounted and rebuilt on each
 * navigation. Holding the thread inside the dock meant walking from Deals to a company threw
 * the conversation away mid-sentence. It lives here instead, in a provider mounted once in the
 * root layout, and is mirrored into sessionStorage so a reload keeps it too.
 *
 * sessionStorage, not localStorage: the questions carry deal values and commissions, and they
 * should not outlive the tab. Closing it, or signing out, clears them. Nothing is sent to the
 * database.
 */

import * as React from "react";

import { ApiError, api } from "@/lib/api";
import type { AskResponse } from "@/lib/types";

export type WriteState = "pending" | "applied" | "discarded";

export interface Turn {
  id: string;
  question: string;
  asked_at: number;
  response: AskResponse | null;
  error: string | null;
  /** Whether the write this turn proposed was applied. Kept on the turn so it survives a
      navigation — a half-confirmed change must not reappear as if it were still waiting. */
  write_state: WriteState;
}

interface Conversation {
  turns: Turn[];
  busy: boolean;
  open: boolean;
  setOpen: (open: boolean) => void;
  ask: (question: string, context?: string) => Promise<void>;
  clear: () => void;
  setWriteState: (turnId: string, state: WriteState) => void;
}

const STORAGE_KEY = "ecolink.ask.session.v1";

const ConversationContext = React.createContext<Conversation | null>(null);

function load(): Turn[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as Turn[]) : [];
  } catch {
    // Private windows and cleared site data both throw here. A lost thread is not worth an error.
    return [];
  }
}

export function ConversationProvider({ children }: { children: React.ReactNode }) {
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  // Read after mount, never during render: the server has no sessionStorage, and reading it
  // while rendering would make the first client paint disagree with the server's markup.
  React.useEffect(() => {
    const saved = load();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (saved.length) setTurns(saved);
  }, []);

  React.useEffect(() => {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(turns));
    } catch {
      // Out of quota, or storage blocked. The thread still works for this page.
    }
  }, [turns]);

  const ask = React.useCallback(async (question: string, context?: string) => {
    const q = question.trim();
    if (!q) return;

    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setTurns((t) => [...t, {
      id, question: q, asked_at: Date.now(), response: null, error: null, write_state: "pending",
    }]);
    setBusy(true);
    try {
      const response = await api.post<AskResponse>("/chat/ask", { question: q, context });
      setTurns((t) => t.map((turn) => (turn.id === id ? { ...turn, response } : turn)));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Something went wrong.";
      setTurns((t) => t.map((turn) => (turn.id === id ? { ...turn, error: message } : turn)));
    } finally {
      setBusy(false);
    }
  }, []);

  const clear = React.useCallback(() => setTurns([]), []);

  const setWriteState = React.useCallback((turnId: string, state: WriteState) => {
    setTurns((t) => t.map((turn) => (turn.id === turnId ? { ...turn, write_state: state } : turn)));
  }, []);

  const value = React.useMemo(
    () => ({ turns, busy, open, setOpen, ask, clear, setWriteState }),
    [turns, busy, open, ask, clear, setWriteState],
  );

  return <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>;
}

export function useConversation(): Conversation {
  const ctx = React.useContext(ConversationContext);
  if (!ctx) throw new Error("useConversation must be used inside <ConversationProvider>");
  return ctx;
}

/** Wipe the thread when a session ends. Called from sign-out. */
export function clearStoredConversation() {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing stored, nothing to clear.
  }
}
