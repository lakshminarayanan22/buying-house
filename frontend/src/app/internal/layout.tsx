"use client";

import { AppShell, type NavItem } from "@/components/AppShell";
import { useRequirePortal } from "@/lib/session";

const NAV: NavItem[] = [
  { href: "/internal", label: "Dashboard" },
  { href: "/internal/suppliers", label: "Suppliers" },
  { href: "/internal/master-data", label: "Master data" },
  // The natural-language editor is Super Admin only; the server enforces it too, so this is
  // purely about not showing a door that will not open.
  { href: "/internal/data-editor", label: "Data editor", roles: ["INTERNAL_SUPER_ADMIN"] },
];

export default function InternalLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useRequirePortal("internal");
  if (loading || !user) return null;
  return <AppShell nav={NAV}>{children}</AppShell>;
}
