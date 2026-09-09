"use client";

/** Small, unstyled-by-default primitives. Everything is a plain element with tokens applied —
 *  no component library, because the whole surface here is forms and tables. */
import * as React from "react";

import { dealTone, isLive, titleCase } from "@/lib/format";

export function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

/* ------------------------------------------------------------------ Card */
export function Card({
  children,
  className,
  rail = false,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { rail?: boolean }) {
  return (
    <div
      {...rest}
      className={cx("relative overflow-hidden rounded-lg border", className)}
      style={{
        background: "var(--surface)",
        borderColor: "var(--border)",
        // A panel bolted onto the hull: lifted off the grid by a shadow, with a
        // hairline of internal light along the top edge.
        boxShadow: "0 1px 0 0 var(--surface-2) inset, 0 8px 24px -18px rgba(0,0,0,.9)",
        ...rest.style,
      }}
    >
      {/* The rail marks a panel as primary — the one you came to this screen to read. */}
      {rail ? (
        <span
          aria-hidden
          className="absolute inset-x-0 top-0 h-px"
          style={{
            background:
              "linear-gradient(90deg, transparent, var(--accent-line) 18%, var(--accent-line) 82%, transparent)",
          }}
        />
      ) : null}
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
    // Primary is a backlit control: it carries its own halo, so it reads as the
    // thing on the panel that is powered.
    primary: {
      background: "var(--accent)",
      color: "var(--accent-fg)",
      borderColor: "var(--accent)",
      boxShadow: "0 0 0 1px var(--accent-line), 0 4px 16px -6px var(--glow)",
    },
    secondary: {
      background: "var(--surface-2)",
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

/**
 * Tailwind resolves conflicting utilities by CSS source order, not by their order in a
 * class string, so a caller's `w-44` silently loses to the base `w-full` and the control
 * renders full width. Every sized filter in the app was doing this. Dropping the default
 * whenever the caller sets a width of their own is enough to settle it.
 */
function widthClass(className?: string) {
  return /(^|\s)(w-|max-w-)/.test(className ?? "") ? "" : "w-full";
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
        className={cx(widthClass(className), "rounded-md border px-2.5 py-1.5 text-sm", className)}
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
      className={cx(widthClass(className), "rounded-md border px-2.5 py-1.5 text-sm", className)}
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
      className={cx(widthClass(className), "rounded-md border px-2.5 py-1.5 text-sm", className)}
      style={{ ...controlStyle, ...rest.style }}
    >
      {children}
    </select>
  );
}

/* ------------------------------------------------------------------ Lamp */
const LAMPS: Record<string, string> = {
  slate: "var(--text-subtle)",
  emerald: "var(--success)",
  sky: "var(--accent)",
  amber: "var(--warning)",
  rose: "var(--danger)",
};

/**
 * An indicator lamp.
 *
 * A dot with a halo the colour of whatever it is reporting. This is the one piece
 * of the console idiom that is load-bearing rather than atmospheric: on a dense
 * table the eye finds a lit dot far faster than it reads a word, so status becomes
 * scannable down a column without anyone having to parse it.
 */
export function Lamp({ tone = "slate", live = false }: { tone?: string; live?: boolean }) {
  const colour = LAMPS[tone] ?? LAMPS.slate;
  return (
    <span
      aria-hidden
      className={cx("inline-block h-[6px] w-[6px] shrink-0 rounded-full", live && "lamp-live")}
      style={{
        background: colour,
        // Two rings: a tight one that reads as the bezel, a wide soft one as spill.
        boxShadow: `0 0 0 2px color-mix(in srgb, ${colour} 22%, transparent), 0 0 7px ${colour}`,
      }}
    />
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
  lamp = false,
  live = false,
}: {
  tone?: string;
  children: React.ReactNode;
  title?: string;
  lamp?: boolean;
  live?: boolean;
}) {
  const palette = TONES[tone] ?? TONES.slate;
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap"
      style={{ background: palette.bg, color: palette.fg }}
    >
      {lamp ? <Lamp tone={tone} live={live} /> : null}
      {children}
    </span>
  );
}

/**
 * A deal, milestone or commission state.
 *
 * Every status in the app went through `dealTone` and `titleCase` at the call site,
 * which meant seven places to keep in step. It is one component now, and it is where
 * the lamp is decided: lit for every state, pulsing only for the ones still running.
 */
export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  return (
    <Badge tone={dealTone(status)} lamp live={isLive(status)}>
      {titleCase(status)}
    </Badge>
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
      className={cx("micro border-b px-3 py-2", align === "right" ? "text-right" : "text-left")}
      style={{ borderColor: "var(--border)" }}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  align = "left",
  readout,
  className,
}: {
  children?: React.ReactNode;
  align?: "left" | "right";
  /** Render as an instrument figure — mono and tabular. Defaults to on for
   *  right-aligned cells, since those are nearly always money or quantity.
   *  Pass false for the handful that are right-aligned prose ("24 days ago"),
   *  where a monospace face just looks broken. */
  readout?: boolean;
  className?: string;
}) {
  const asFigure = readout ?? align === "right";
  return (
    <td
      className={cx(
        "border-b px-3 py-2 align-top",
        align === "right" ? "text-right" : "text-left",
        asFigure && "readout",
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
