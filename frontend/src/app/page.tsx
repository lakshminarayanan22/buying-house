"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { homePathFor, useSession } from "@/lib/session";

export default function Home() {
  const { user, loading } = useSession();
  const router = useRouter();

  React.useEffect(() => {
    if (!loading) router.replace(homePathFor(user));
  }, [loading, user, router]);

  return (
    <main className="grid min-h-dvh place-items-center">
      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        Loading…
      </p>
    </main>
  );
}
