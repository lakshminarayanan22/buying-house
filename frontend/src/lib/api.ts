"use client";

/**
 * Thin API client.
 *
 * The session token lives in localStorage rather than a cookie because the backend is a
 * separate origin and issues a bearer token; there is no cookie for it to set. A 401 clears
 * the session and bounces to the login screen, so a revoked user cannot linger in a stale UI.
 */
import type { CurrentUser } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
const TOKEN_KEY = "bh.session";

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(status: number, message: string, payload?: unknown) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

/** Extract a readable message from FastAPI's several error shapes. */
function messageFrom(payload: unknown, fallback: string): string {
  if (typeof payload === "string") return payload;
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // Pydantic validation errors arrive as a list of {loc, msg}.
    if (Array.isArray(detail)) {
      return detail
        .map((d) => {
          const item = d as { loc?: unknown[]; msg?: string };
          const field = Array.isArray(item.loc) ? item.loc.slice(-1)[0] : "";
          return field ? `${field}: ${item.msg}` : item.msg;
        })
        .filter(Boolean)
        .join("; ");
    }
    if (detail && typeof detail === "object" && "question" in detail) {
      return String((detail as { question: unknown }).question);
    }
  }
  return fallback;
}

async function request<T>(
  path: string,
  init: RequestInit & { query?: Record<string, unknown> } = {},
): Promise<T> {
  const { query, ...rest } = init;

  let url = `${BASE}${path}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      // Repeated keys are how the directory sends multi-select facets.
      if (Array.isArray(value)) value.forEach((v) => params.append(key, String(v)));
      else params.append(key, String(value));
    }
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }

  const headers = new Headers(rest.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (rest.body && !(rest.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(url, { ...rest, headers });

  if (response.status === 401) {
    setToken(null);
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      // A hard navigation on purpose: this module has no router, and a revoked session should
      // drop every piece of in-memory state rather than soft-navigate with it intact.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login";
    }
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }

  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new ApiError(
      response.status,
      messageFrom(payload, `Request failed (${response.status})`),
      payload,
    );
  }

  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) return (await response.blob()) as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T,>(path: string, query?: Record<string, unknown>) =>
    request<T>(path, { method: "GET", query }),
  post: <T,>(path: string, body?: unknown, query?: Record<string, unknown>) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined, query }),
  put: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  del: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
};

export async function login(email: string, password: string): Promise<CurrentUser> {
  const session = await request<{ access_token: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
    headers: { "Content-Type": "application/json" },
  });
  setToken(session.access_token);
  return api.get<CurrentUser>("/auth/me");
}

export async function requestOtp(phone: string): Promise<string> {
  const result = await request<{ detail: string }>("/auth/otp/request", {
    method: "POST",
    body: JSON.stringify({ phone }),
    headers: { "Content-Type": "application/json" },
  });
  return result.detail;
}

export async function verifyOtp(phone: string, code: string): Promise<CurrentUser> {
  const session = await request<{ access_token: string }>("/auth/otp/verify", {
    method: "POST",
    body: JSON.stringify({ phone, code }),
    headers: { "Content-Type": "application/json" },
  });
  setToken(session.access_token);
  return api.get<CurrentUser>("/auth/me");
}

export async function logout() {
  try {
    await api.post("/auth/logout");
  } finally {
    setToken(null);
  }
}
