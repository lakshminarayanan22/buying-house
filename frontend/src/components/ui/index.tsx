"use client";

/** Small, unstyled-by-default primitives. Everything is a plain element with tokens applied —
 *  no component library, because the whole surface here is forms and tables. */
import * as React from "react";

export function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ Card */
export function Card({
  children,
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className={cx("rounded-lg border", className)}
      style={{ background: "var(--surface)", borderColor: "var(--border)", ...rest.style }}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  actions,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div
      className="flex items-start justify-between gap-4 border-b px-5 py-4"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="min-w-0">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {subtitle ? (
          <p className="mt-0.5 text-xs" style={{ color: "var(--text-muted)" }}>
            {subtitle}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/* ---------------------------------------------------------------- Button */
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  disabled,
  children,
  className,
  ...rest
}: ButtonProps) {
  const palette: Record<string, React.CSSProperties> = {
    primary: { background: "var(--accent)", color: "var(--accent-fg)", borderColor: "var(--accent)" },
    secondary: {
      background: "var(--surface)",
      color: "var(--text)",
      borderColor: "var(--border-strong)",
    },
    ghost: { background: "transparent", color: "var(--text-muted)", borderColor: "transparent" },
    danger: { background: "var(--danger)", color: "#fff", borderColor: "var(--danger)" },
  };

  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition-opacity",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-1.5 text-sm",
        (disabled || loading) && "cursor-not-allowed opacity-55",
        className,
      )}
      style={{ ...palette[variant], ...rest.style }}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
}

export function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  );
}

/* ----------------------------------------------------------------- Field */
export function Field({
  label,
  hint,
  error,
  required,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium" style={{ color: "var(--text-muted)" }}>
        {label}
        {required ? <span style={{ color: "var(--danger)" }}> *</span> : null}
      </span>
      {children}
      {error ? (
        <span className="mt-1 block text-xs" style={{ color: "var(--danger)" }}>
          {error}
        </span>
      ) : hint ? (
        <span className="mt-1 block text-xs" style={{ color: "var(--text-subtle)" }}>
          {hint}
        </span>
      ) : null}
    </label>
  );
}

const controlStyle: React.CSSProperties = {
  background: "var(--surface)",
  borderColor: "var(--border-strong)",
  color: "var(--text)",
};

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return (
      <input
        ref={ref}
        {...rest}
        className={cx("w-full rounded-md border px-2.5 py-1.5 text-sm", className)}
        style={{ ...controlStyle, ...rest.style }}
      />
    );
  },
);

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...rest }, ref) {
  return (
    <textarea
      ref={ref}
      {...rest}
      className={cx("w-full rounded-md border px-2.5 py-1.5 text-sm", className)}
      style={{ ...controlStyle, ...rest.style }}
    />
  );
});

export function Select({
  className,
  children,
  ...rest
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...rest}
      className={cx("w-full rounded-md border px-2.5 py-1.5 text-sm", className)}
      style={{ ...controlStyle, ...rest.style }}
    >
      {children}
    </select>
  );
}

/* ----------------------------------------------------------------- Badge */
const TONES: Record<string, { bg: string; fg: string }> = {
  slate: { bg: "var(--surface-2)", fg: "var(--text-muted)" },
  emerald: { bg: "var(--success-soft)", fg: "var(--success)" },
  sky: { bg: "var(--accent-soft)", fg: "var(--accent)" },
  amber: { bg: "var(--warning-soft)", fg: "var(--warning)" },
  rose: { bg: "var(--danger-soft)", fg: "var(--danger)" },
};

export function Badge({
  tone = "slate",
  children,
  title,
}: {
  tone?: string;
  children: React.ReactNode;
  title?: string;
}) {
  const palette = TONES[tone] ?? TONES.slate;
  return (
    <span
      title={title}
      className="inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap"
      style={{ background: palette.bg, color: palette.fg }}
    >
      {children}
    </span>
  );
}

/* --------------------------------------------------------------- Feedback */
export function Alert({
  tone = "rose",
  children,
}: {
  tone?: "rose" | "amber" | "emerald" | "sky";
  children: React.ReactNode;
}) {
  const palette = TONES[tone] ?? TONES.rose;
  return (
    <div
      role="alert"
      className="rounded-md px-3 py-2 text-sm"
      style={{ background: palette.bg, color: palette.fg }}
    >
      {children}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-5 py-12 text-center">
      <p className="text-sm font-medium">{title}</p>
      {hint ? (
        <p className="mx-auto mt-1 max-w-md text-xs" style={{ color: "var(--text-muted)" }}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/* ----------------------------------------------------------------- Table */
export function Table({ children }: { children: React.ReactNode }) {
  // Wide tables scroll inside their own container; the page body never scrolls sideways.
  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  );
}

export function Th({
  children,
  align = "left",
}: {
  children?: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      className={cx(
        "border-b px-3 py-2 text-[11px] font-semibold tracking-wide uppercase",
        align === "right" ? "text-right" : "text-left",
      )}
      style={{ borderColor: "var(--border)", color: "var(--text-subtle)" }}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  align = "left",
  className,
}: {
  children?: React.ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <td
      className={cx(
        "border-b px-3 py-2 align-top",
        align === "right" ? "text-right tabular" : "text-left",
        className,
      )}
      style={{ borderColor: "var(--border)" }}
    >
      {children}
    </td>
  );
}

/* ------------------------------------------------------------ Progress */
export function CompletenessBar({ value }: { value: number }) {
  // Colour tracks the thresholds that actually gate participation, not arbitrary bands.
  const tone = value >= 80 ? "var(--success)" : value >= 50 ? "var(--warning)" : "var(--danger)";
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-1.5 w-24 overflow-hidden rounded-full"
        style={{ background: "var(--border)" }}
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${Math.min(100, Math.max(0, value))}%`, background: tone }}
        />
      </div>
      <span className="tabular text-xs" style={{ color: "var(--text-muted)" }}>
        {value}%
      </span>
    </div>
  );
}

/* ------------------------------------------------------------- FileUpload */
/**
 * A real button that opens the file picker.
 *
 * A bare `<input type="file">` renders as the browser's own control — a grey "Choose file"
 * with "No file chosen" beside it — which looks like nothing else on the page and reads as
 * unfinished. The input is kept for the picker and hidden; the button is what people see.
 */
export function FileUpload({
  label = "Upload a file",
  accept,
  busy = false,
  disabled = false,
  onFile,
}: {
  label?: string;
  accept?: string;
  busy?: boolean;
  disabled?: boolean;
  onFile: (file: File) => void | Promise<void>;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [name, setName] = React.useState<string | null>(null);

  return (
    <div className="flex items-center gap-2">
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="sr-only"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          setName(file.name);
          await onFile(file);
          // Reset so re-picking the same file fires change again.
          if (inputRef.current) inputRef.current.value = "";
        }}
      />
      <Button
        type="button"
        size="sm"
        loading={busy}
        disabled={disabled || busy}
        onClick={() => inputRef.current?.click()}
      >
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path
            d="M8 11V3M8 3L5 6M8 3l3 3M3 11v1.5A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5V11"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        {busy ? "Uploading…" : label}
      </Button>
      {name && !busy ? (
        <span className="truncate text-[11px]" style={{ color: "var(--text-subtle)" }}>
          {name}
        </span>
      ) : null}
    </div>
  );
}
