"use client";

import { Lamp } from "@/components/ui";

/** A person's Google photo, or their initials when there isn't one. */
export function Avatar({ name, url, size = 28 }: { name: string; url: string | null; size?: number }) {
  const initials = name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return url ? (
    // Google profile photos live on googleusercontent.com; next/image would need that host
    // allow-listed in config for a 28px circle, which isn't worth it.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt="" width={size} height={size} referrerPolicy="no-referrer"
         className="shrink-0 rounded-full" style={{ width: size, height: size }} />
  ) : (
    <span
      className="grid shrink-0 place-items-center rounded-full text-[10px] font-semibold"
      style={{ width: size, height: size, background: "var(--accent-soft)", color: "var(--accent)" }}
    >
      {initials || <Lamp />}
    </span>
  );
}
