import type { Metadata } from "next";

import { SessionProvider } from "@/lib/session";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ecolink",
  description: "Companies, deals and commission tracking.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: the boot script below stamps data-theme on <html> before
    // React hydrates, so the server markup (no attribute) never matches the client. The
    // warning is expected here and applies only to this element, not its subtree.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Applies the saved palette before first paint, so there is no flash of the default. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
