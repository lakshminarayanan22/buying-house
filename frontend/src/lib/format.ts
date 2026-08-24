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
