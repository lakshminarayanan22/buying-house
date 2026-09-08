/** Display helpers shared across screens. */

export function titleCase(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-IN").format(value);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

/** Renders a JSON-ish cell value from the change-preview diff. */
export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "∅";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const STATUS_TONES: Record<string, string> = {
  VERIFIED: "emerald",
  APPLIED: "emerald",
  SUBMITTED: "sky",
  UNDER_REVIEW: "sky",
  PREVIEWED: "sky",
  DRAFT: "slate",
  INVITED: "slate",
  NEEDS_INFO: "amber",
  PENDING: "amber",
  CONFLICTED: "amber",
  REJECTED: "rose",
  SUSPENDED: "rose",
  EXPIRED: "rose",
  DISCARDED: "slate",
};

export function statusTone(status: string | null | undefined): string {
  return STATUS_TONES[status ?? ""] ?? "slate";
}

export function money(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency, maximumFractionDigits: 0,
  }).format(value);
}

/** "3 days ago" / "today" — the gone-quiet list is read in days, not dates. */
export function daysAgo(days: number | null | undefined): string {
  if (days === null || days === undefined) return "—";
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

const DEAL_TONES: Record<string, string> = {
  LEAD: "slate", NEGOTIATING: "amber", AGREED: "sky", IN_PROGRESS: "sky",
  SHIPPED: "emerald", COMPLETED: "emerald", ON_HOLD: "amber", LOST: "rose",
  DUE: "amber", INVOICED: "sky", RECEIVED: "emerald", NOT_DUE: "slate",
  WRITTEN_OFF: "rose", PENDING: "slate", BLOCKED: "rose", DONE: "emerald", SKIPPED: "slate",
  ACTIVE: "emerald", INACTIVE: "slate", BLACKLISTED: "rose",
};

export function dealTone(status: string | null | undefined): string {
  return DEAL_TONES[status ?? ""] ?? "slate";
}
