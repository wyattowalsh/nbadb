import "./global.css";
import Script from "next/script";
import { RootProvider } from "fumadocs-ui/provider/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import { Barlow_Condensed, IBM_Plex_Mono, Inter } from "next/font/google";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import {
  siteDescription,
  siteName,
  siteOrigin,
  siteTitle,
} from "@/lib/site-config";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans-var",
});

const barlowCondensed = Barlow_Condensed({
  subsets: ["latin"],
  variable: "--font-display-var",
  weight: ["400", "500", "600", "700"],
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-mono-var",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  metadataBase: new URL(siteOrigin),
  applicationName: siteName,
  title: {
    template: `%s | ${siteName}`,
    default: siteTitle,
  },
  description: siteDescription,
  alternates: {
    canonical: "/",
  },
  keywords: [
    "NBA data",
    "basketball analytics",
    "DuckDB",
    "star schema",
    "endpoint coverage",
    "lineage",
    "shot charts",
    "docs",
  ],
  openGraph: {
    type: "website",
    siteName,
    title: siteTitle,
    description: siteDescription,
    url: siteOrigin,
  },
  twitter: {
    card: "summary_large_image",
    title: siteTitle,
    description: siteDescription,
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${barlowCondensed.variable} ${ibmPlexMono.variable}`}
      suppressHydrationWarning
    >
      <body className="nba-site flex min-h-screen flex-col bg-background text-foreground antialiased">
        <RootProvider
          search={{ enabled: true }}
          theme={{
            attribute: "class",
            defaultTheme: "dark",
            enableSystem: true,
          }}
        >
          {children}
        </RootProvider>
        {process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID && (
          <Script
            async
            defer
            data-website-id={process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID}
            src={
              process.env.NEXT_PUBLIC_UMAMI_HOST
                ? `${process.env.NEXT_PUBLIC_UMAMI_HOST}/script.js`
                : "https://cloud.umami.is/script.js"
            }
          />
        )}
        <SpeedInsights />
      </body>
    </html>
  );
}
