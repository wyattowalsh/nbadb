import "./global.css";
import Script from "next/script";
import { RootProvider } from "fumadocs-ui/provider/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import { IBM_Plex_Mono, Noto_Sans, IBM_Plex_Sans } from "next/font/google";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import {
  siteDescription,
  siteName,
  siteOrigin,
  siteTitle,
} from "@/lib/site-config";
import { cn } from "@/lib/utils";

const ibmPlexSansHeading = IBM_Plex_Sans({
  subsets: ["latin"],
  variable: "--font-heading",
  display: "swap",
});

const notoSans = Noto_Sans({ subsets: ["latin"], variable: "--font-sans", display: "swap" });

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-mono-var",
  weight: ["400", "500", "600", "700"],
  display: "swap",
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
        url: `${siteOrigin}/opengraph-image.png`,
        width: 1200,
        height: 630,
        alt: `${siteName} documentation`,
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: siteTitle,
    description: siteDescription,
    images: [`${siteOrigin}/opengraph-image.png`],
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={cn(
        ibmPlexMono.variable,
        notoSans.variable,
        ibmPlexSansHeading.variable,
        "font-sans",
      )}
      suppressHydrationWarning
    >
      <body className="flex min-h-screen flex-col bg-background text-foreground antialiased">
        <RootProvider
          search={{
            enabled: true,
            links: [
              ["Schema Reference", "/docs/schema"],
              ["Endpoint Coverage", "/docs/endpoints"],
              ["Data Dictionary", "/docs/data-dictionary"],
              ["Lineage Explorer", "/docs/lineage"],
              ["Guides", "/docs/guides"],
            ],
            options: {
              delayMs: 100,
              allowClear: true,
            },
          }}
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
