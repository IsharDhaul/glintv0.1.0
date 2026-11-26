import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fontsource/atkinson-hyperlegible-next/400.css";
import "@fontsource/atkinson-hyperlegible-next/500.css";
import "@fontsource/atkinson-hyperlegible-next/600.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import { InlineScript } from "@/components/InlineScript";
import { AppFooter, AppHeader } from "@/components/layout/AppHeader";
import { SyntheticBanner } from "@/components/SyntheticBanner";
import { SyntheticBuildBanner } from "@/components/SyntheticBuildBanner";
import { isMockMode } from "@/lib/api/config";
import { PREFS_SCRIPT } from "@/lib/prefs";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Glint",
  description: "Fundamentals-first US stock screener. Educational tool. Not investment advice.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      data-density="compact"
      // PREFS_SCRIPT rewrites data-density before hydration.
      suppressHydrationWarning
    >
      <head>
        <InlineScript html={PREFS_SCRIPT} />
      </head>
      <body className="flex min-h-dvh flex-col antialiased">
        {isMockMode() && <SyntheticBanner />}
        <Providers>
          {!isMockMode() && <SyntheticBuildBanner />}
          <AppHeader />
          <div className="flex-1">{children}</div>
          <AppFooter />
        </Providers>
      </body>
    </html>
  );
}
