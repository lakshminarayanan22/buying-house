"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSession } from "@/lib/session";
import { Badge, Button, cx } from "@/components/ui";
import { titleCase } from "@/lib/format";

export interface NavItem {
  href: string;
  label: string;
  /** Roles that may see this link. Omitted means every role in the portal. */
  roles?: string[];
}

export function AppShell({
  nav,
  children,
}: {
  nav: NavItem[];
  children: React.ReactNode;
}) {
  const { user, signOut, t } = useSession();
  const pathname = usePathname();

  const visible = nav.filter((item) => !item.roles || (user && item.roles.includes(user.role)));

  return (
    <div className="min-h-dvh">
      <header
        className="sticky top-0 z-20 border-b backdrop-blur"
        style={{ background: "color-mix(in srgb, var(--surface) 88%, transparent)", borderColor: "var(--border)" }}
      >
        <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-5 py-2.5">
          <Link href="/" className="text-sm font-semibold tracking-tight whitespace-nowrap">
            {t("app.name")}
          </Link>

          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
            {visible.map((item) => {
              const active =
                pathname === item.href ||
                (item.href !== "/internal" && pathname.startsWith(`${item.href}/`));
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cx(
                    "rounded-md px-2.5 py-1.5 text-sm whitespace-nowrap transition-colors",
                    active ? "font-medium" : "",
                  )}
                  style={{
                    background: active ? "var(--accent-soft)" : "transparent",
                    color: active ? "var(--accent)" : "var(--text-muted)",
                  }}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex shrink-0 items-center gap-3">
            {user ? (
              <div className="hidden text-right sm:block">
                <div className="text-xs font-medium">{user.name}</div>
                <div className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                  {titleCase(user.role.replace("INTERNAL_", ""))}
                  {user.org_name ? ` · ${user.org_name}` : ""}
                </div>
              </div>
            ) : null}
            <Button size="sm" variant="ghost" onClick={() => void signOut()}>
              {t("nav.signOut")}
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-5 py-6">{children}</main>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle ? (
          <div className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
            {subtitle}
          </div>
        ) : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/** Marks where a value came from — a merchandiser's visit or the factory's own form.
 *  The distinction drives how much the matching engine should trust it, so it is visible. */
export function SourceBadge({ source }: { source: string | null | undefined }) {
  if (!source) return null;
  const map: Record<string, { tone: string; label: string; title: string }> = {
    SELF_REPORTED: {
      tone: "slate",
      label: "Self-reported",
      title: "Entered by the supplier. Not yet checked by anyone.",
    },
    INTERNAL_VERIFIED: {
      tone: "sky",
      label: "Checked by us",
      title: "Entered or confirmed by our team.",
    },
    OBSERVED: {
      tone: "emerald",
      label: "Observed",
      title: "Derived from real transactions, not from a claim.",
    },
  };
  const meta = map[source];
  if (!meta) return null;
  return (
    <Badge tone={meta.tone} title={meta.title}>
      {meta.label}
    </Badge>
  );
}
