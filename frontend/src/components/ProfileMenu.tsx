"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Avatar } from "@/components/Avatar";
import { Badge } from "@/components/ui";
import { titleCase } from "@/lib/format";
import { useSession } from "@/lib/session";
import { APPEARANCES, appearanceStore, writeAppearance } from "@/lib/theme";

/**
 * The avatar at the top right, and the menu behind it — who you are, your account, how the
 * app looks, and the way out.
 *
 * Appearance and sign-out used to sit loose in the header as their own buttons. They're
 * things you do rarely and about yourself, which is exactly what this menu is for, so they
 * moved in here and the header got quieter.
 */
export function ProfileMenu() {
  const { user, signOut } = useSession();
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);
  const root = React.useRef<HTMLDivElement>(null);
  const trigger = React.useRef<HTMLButtonElement>(null);
  const appearance = React.useSyncExternalStore(
    appearanceStore.subscribe,
    appearanceStore.getSnapshot,
    appearanceStore.getServerSnapshot,
  );

  // Close on navigation — following a link from the menu shouldn't leave it hanging open.
  const [lastPath, setLastPath] = React.useState(pathname);
  if (pathname !== lastPath) {
    setLastPath(pathname);
    setOpen(false);
  }

  React.useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();   // hand focus back to where it came from
      }
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;

  return (
    <div ref={root} className="relative">
      <button
        ref={trigger}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${user.name}`}
        className="flex items-center gap-2 rounded-full py-0.5 pr-0.5 pl-2 transition-colors"
        style={{
          background: open ? "var(--accent-soft)" : "transparent",
          boxShadow: open ? "0 0 0 1px var(--accent-line)" : undefined,
        }}
      >
        <span className="hidden text-right sm:block">
          <span className="block text-xs font-medium">{user.name}</span>
          <span className="micro block">{titleCase(user.role)}</span>
        </span>
        <Avatar name={user.name} url={user.avatar_url} size={28} />
      </button>

      {open ? (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 z-40 mt-2 w-72 overflow-hidden rounded-lg border shadow-xl"
          style={{
            background: "var(--surface)",
            borderColor: "var(--border-strong)",
            boxShadow: "0 18px 48px -18px rgba(0,0,0,.8), 0 0 0 1px var(--accent-line)",
          }}
        >
          {/* Who's signed in */}
          <div className="flex items-center gap-3 border-b px-4 py-3" style={{ borderColor: "var(--border)" }}>
            <Avatar name={user.name} url={user.avatar_url} size={40} />
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="truncate text-sm font-semibold">{user.name}</span>
                <Badge tone="sky">{titleCase(user.role)}</Badge>
              </div>
              <div className="readout truncate text-[11px]" style={{ color: "var(--text-muted)" }}>
                {user.email}
              </div>
              <div className="mt-0.5 text-[10px]" style={{ color: "var(--text-subtle)" }}>
                {user.google_linked ? "Google account" : "Password account"}
                {user.google_linked && user.has_password ? " · password added" : ""}
              </div>
            </div>
          </div>

          <div className="py-1">
            <MenuLink href="/account" icon={<PersonIcon />}>
              Your account
              <span className="block text-[11px]" style={{ color: "var(--text-subtle)" }}>
                Profile and password
              </span>
            </MenuLink>
          </div>

          {/* Appearance: three states, so a segmented control rather than a toggle. */}
          <div className="border-t px-4 py-3" style={{ borderColor: "var(--border)" }}>
            <div className="micro mb-2">Appearance</div>
            <div
              role="radiogroup"
              aria-label="Appearance"
              className="grid grid-cols-3 gap-1 rounded-md p-0.5"
              style={{ background: "var(--surface-2)", boxShadow: "inset 0 0 0 1px var(--border)" }}
            >
              {APPEARANCES.map((a) => {
                const on = a.key === appearance;
                return (
                  <button
                    key={a.key}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    title={a.hint}
                    onClick={() => writeAppearance(a.key)}
                    className="rounded px-2 py-1 text-[11px] font-medium transition-colors"
                    style={{
                      background: on ? "var(--surface)" : "transparent",
                      color: on ? "var(--accent)" : "var(--text-muted)",
                      boxShadow: on ? "0 0 0 1px var(--accent-line)" : undefined,
                    }}
                  >
                    {a.key === "dark" ? "Dark" : a.key === "light" ? "Light" : "System"}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="border-t py-1" style={{ borderColor: "var(--border)" }}>
            <button
              type="button"
              role="menuitem"
              onClick={() => void signOut()}
              className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm transition-colors hover:bg-[var(--surface-2)]"
            >
              <SignOutIcon />
              Sign out
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MenuLink({ href, icon, children }: { href: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      role="menuitem"
      className="flex items-start gap-3 px-4 py-2 text-sm transition-colors hover:bg-[var(--surface-2)]"
    >
      <span className="mt-0.5">{icon}</span>
      <span>{children}</span>
    </Link>
  );
}

function PersonIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden
         stroke="var(--text-muted)" strokeWidth="1.4" strokeLinecap="round">
      <circle cx="8" cy="5.5" r="2.75" />
      <path d="M2.75 13.5c.9-2.4 2.9-3.75 5.25-3.75s4.35 1.35 5.25 3.75" />
    </svg>
  );
}

function SignOutIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden
         stroke="var(--text-muted)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 13.5H3.5a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1H6" />
      <path d="M10.5 11 13.5 8l-3-3M13.5 8H6" />
    </svg>
  );
}
