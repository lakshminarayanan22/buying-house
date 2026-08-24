"use client";

import { AppShell, type NavItem } from "@/components/AppShell";
import { useRequirePortal } from "@/lib/session";

const NAV: NavItem[] = [{ href: "/supplier", label: "My profile" }];

export default function SupplierLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useRequirePortal("supplier");
  if (loading || !user) return null;
  return <AppShell nav={NAV}>{children}</AppShell>;
}
