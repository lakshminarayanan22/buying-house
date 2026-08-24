import type { Metadata } from "next";

import { SessionProvider } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = {
  title: "Buying House",
  description:
    "Sourcing platform connecting brands and suppliers, with an internal merchandising console.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
