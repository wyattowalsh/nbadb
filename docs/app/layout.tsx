import "./global.css";
import Script from "next/script";
import { RootProvider } from "fumadocs-ui/provider/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import type { Metadata, Viewport } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import type { ReactNode } from "react";
import {
  siteDescription,
  siteName,
  siteOrigin,
  siteTitle,
} from "@/lib/site-config";

const bodyFont = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-body",
});

const headingFont = Space_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
  weight: ["500", "700"],
});

export const metadata: Metadata = {
  metadataBase: new URL(siteOrigin),
  applicationName: siteName,
  title: {
    template: `%s | ${siteName}`,
    default: siteTitle,
  },
  description: siteDescription,
  icons: {
    icon: [{ url: "/favicon.ico", sizes: "any" }],
    apple: "/apple-icon.png",
  },
  manifest: "/site.webmanifest",
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
    images: [
      {
        url: "/opengraph-image",
        width: 1200,
        height: 630,
        alt: `${siteName} warehouse documentation overview`,
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: siteTitle,
    description: siteDescription,
    images: ["/opengraph-image"],
  },
};

export const viewport: Viewport = {
  colorScheme: "dark light",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#09090b" },
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const showSpeedInsights = process.env.VERCEL === "1";

  return (
    <html
      lang="en"
      className={`${bodyFont.variable} ${headingFont.variable} font-sans`}
      suppressHydrationWarning
    >
      <body className="flex min-h-screen flex-col bg-background text-foreground antialiased">
        <a
          href="#main-content"
          className="sr-only fixed left-4 top-4 z-[100] rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-lg focus:not-sr-only"
        >
          Skip to main content
        </a>
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
        {showSpeedInsights && <SpeedInsights />}
      </body>
    </html>
  );
}
