"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSession } from "@/lib/session";
import { Badge, Button, cx } from "@/components/ui";
import { titleCase } from "@/lib/format";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/deals", label: "Deals" },
  { href: "/companies", label: "Companies" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useSession();
  const pathname = usePathname();

  return (
    <div className="min-h-dvh">
      <header
        className="sticky top-0 z-20 border-b backdrop-blur"
        style={{
          background: "color-mix(in srgb, var(--surface) 88%, transparent)",
          borderColor: "var(--border)",
        }}
      >
        <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-5 py-2.5">
          <Link href="/" className="text-sm font-semibold tracking-tight whitespace-nowrap">
            Ecolink
          </Link>

          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
            {NAV.map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/"
                  : pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cx(
                    "rounded-md px-2.5 py-1.5 text-sm whitespace-nowrap transition-colors",
                    active && "font-medium",
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
                  {titleCase(user.role)}
                </div>
              </div>
            ) : null}
            <Button size="sm" variant="ghost" onClick={() => void signOut()}>
              Sign out
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

/** Buyer, supplier, processor — the role a company plays on one deal. */
export function RoleBadge({ role }: { role: string }) {
  const tone: Record<string, string> = {
    BUYER: "sky",
    SUPPLIER: "emerald",
    PROCESSOR: "amber",
    INPUT_SUPPLIER: "slate",
    OTHER: "slate",
  };
  return <Badge tone={tone[role] ?? "slate"}>{titleCase(role)}</Badge>;
}
