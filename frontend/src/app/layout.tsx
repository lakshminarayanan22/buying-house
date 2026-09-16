import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Instrument_Sans } from "next/font/google";

import { ConversationProvider } from "@/lib/conversation";
import { SessionProvider } from "@/lib/session";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";
import "./globals.css";

// Self-hosted at build time, so no request leaves for Google and nothing shifts on load.
// Three faces, one job each: names, prose, and numbers.
const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-instrument-sans",
  display: "swap",
});

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Ecolink",
  description: "Companies, deals and commission tracking.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: the boot script below stamps data-theme on <html> before
    // React hydrates, so the server markup (no attribute) never matches the client. The
    // warning is expected here and applies only to this element, not its subtree.
    <html
      lang="en"
      suppressHydrationWarning
      className={`${instrumentSans.variable} ${plexSans.variable} ${plexMono.variable}`}
    >
      <head>
        {/* Applies the saved palette before first paint, so there is no flash of the default. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body>
        {/* Above the pages on purpose: each screen mounts its own AppShell, so anything held
            inside the dock would be thrown away on every navigation. */}
        <SessionProvider>
          <ConversationProvider>{children}</ConversationProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
