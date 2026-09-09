"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { AskDock } from "@/components/AskDock";
import { AppearanceToggle } from "@/components/AppearanceToggle";
import { BrandMark } from "@/components/BrandMark";
import { useSession } from "@/lib/session";
import { Badge, Button, Lamp, cx } from "@/components/ui";
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
          background: "color-mix(in srgb, var(--surface) 82%, transparent)",
          borderColor: "var(--border)",
          // A thread of accent light along the bottom edge, so the bar reads as the
          // lit rim of the console rather than a rule drawn under the nav.
          boxShadow: "0 1px 0 0 var(--accent-line), 0 10px 30px -22px rgba(0,0,0,.9)",
        }}
      >
        <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-5 py-2.5">
          <Link
            href="/"
            className="flex items-center gap-2.5 text-sm font-semibold whitespace-nowrap"
            title={user ? "Ecolink — link nominal" : "Ecolink — connecting"}
          >
            <BrandMark />
            <span style={{ letterSpacing: "0.16em" }}>ECOLINK</span>
            <Lamp tone={user ? "emerald" : "amber"} live={!user} />
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
                    boxShadow: active ? "0 0 0 1px var(--accent-line)" : undefined,
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
                <div className="micro">{titleCase(user.role)}</div>
              </div>
            ) : null}
            <AppearanceToggle />
            <Button size="sm" variant="ghost" onClick={() => void signOut()}>
              Sign out
            </Button>
          </div>
        </div>
      </header>

      {/* pb-28 leaves room for the docked composer, which is fixed over the page. */}
      <main className="mx-auto max-w-[1400px] px-5 pt-6 pb-28">{children}</main>
      <AskDock />
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
