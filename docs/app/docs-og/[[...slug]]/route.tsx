import { ImageResponse } from "next/og";
import { siteMetrics } from "@/lib/site-metrics.generated";
import { getSectionMeta, siteName, type SectionId } from "@/lib/site-config";
import { source } from "@/lib/source";

type SectionTheme = {
  bgStart: string;
  bgMid: string;
  bgEnd: string;
  accent: string;
  accentSoft: string;
  secondary: string;
  frame: string;
  panel: string;
  line: string;
};

const sectionThemes: Record<SectionId, SectionTheme> = {
  core: {
    bgStart: "#07121E",
    bgMid: "#102742",
    bgEnd: "#173A57",
    accent: "#D75711",
    accentSoft: "rgba(215, 87, 17, 0.26)",
    secondary: "#3C6C94",
    frame: "rgba(235, 236, 241, 0.16)",
    panel: "rgba(8, 19, 31, 0.74)",
    line: "rgba(235, 236, 241, 0.18)",
  },
  schema: {
    bgStart: "#08111B",
    bgMid: "#14263A",
    bgEnd: "#263C58",
    accent: "#BA9958",
    accentSoft: "rgba(186, 153, 88, 0.26)",
    secondary: "#D75711",
    frame: "rgba(235, 236, 241, 0.16)",
    panel: "rgba(7, 18, 30, 0.74)",
    line: "rgba(235, 236, 241, 0.18)",
  },
  "data-dictionary": {
    bgStart: "#0A1420",
    bgMid: "#1A2A3E",
    bgEnd: "#2D4257",
    accent: "#BA9958",
    accentSoft: "rgba(186, 153, 88, 0.24)",
    secondary: "#EBECF1",
    frame: "rgba(235, 236, 241, 0.16)",
    panel: "rgba(8, 19, 31, 0.76)",
    line: "rgba(235, 236, 241, 0.18)",
  },
  diagrams: {
    bgStart: "#07101A",
    bgMid: "#13293E",
    bgEnd: "#1C4362",
    accent: "#3C6C94",
    accentSoft: "rgba(60, 108, 148, 0.26)",
    secondary: "#D75711",
    frame: "rgba(235, 236, 241, 0.16)",
    panel: "rgba(8, 19, 31, 0.75)",
    line: "rgba(235, 236, 241, 0.18)",
  },
  endpoints: {
    bgStart: "#0A111A",
    bgMid: "#1E2B39",
    bgEnd: "#4A362F",
    accent: "#D75711",
    accentSoft: "rgba(215, 87, 17, 0.28)",
    secondary: "#BA9958",
    frame: "rgba(235, 236, 241, 0.16)",
    panel: "rgba(8, 19, 31, 0.76)",
    line: "rgba(235, 236, 241, 0.18)",
  },
  lineage: {
    bgStart: "#07121E",
    bgMid: "#11263B",
    bgEnd: "#1E3E52",
    accent: "#3C6C94",
    accentSoft: "rgba(60, 108, 148, 0.28)",
    secondary: "#BA9958",
    frame: "rgba(235, 236, 241, 0.16)",
    panel: "rgba(8, 19, 31, 0.76)",
    line: "rgba(235, 236, 241, 0.18)",
  },
  guides: {
    bgStart: "#08121C",
    bgMid: "#16283C",
    bgEnd: "#2A4058",
    accent: "#D75711",
    accentSoft: "rgba(215, 87, 17, 0.24)",
    secondary: "#3C6C94",
    frame: "rgba(235, 236, 241, 0.16)",
    panel: "rgba(8, 19, 31, 0.76)",
    line: "rgba(235, 236, 241, 0.18)",
  },
};

const OG_FONT_STACK =
  "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

export async function GET(
  request: Request,
  props: { params: Promise<{ slug?: string[] }> },
) {
  void request;

  const params = await props.params;
  const page = source.getPage(params.slug);
  const section = getSectionMeta(params.slug);

  const title = page?.data.title ?? section.label;
  const description = page?.data.description ?? section.blurb;
  const theme = sectionThemes[section.id];
  const titleSize = title.length > 32 ? 84 : title.length > 22 ? 94 : 104;
  const sectionStats = section.stats.slice(0, 3);
  const footerItems = [
    section.cue,
    `${siteMetrics[0]?.value ?? "154"} ${siteMetrics[0]?.label.toLowerCase() ?? "extractors"}`,
    `${siteMetrics[1]?.value ?? "96"} ${siteMetrics[1]?.label.toLowerCase() ?? "models"}`,
    "DuckDB",
  ];

  return new ImageResponse(
    <div
      style={{
        display: "flex",
        width: "100%",
        height: "100%",
        background: `linear-gradient(135deg, ${theme.bgStart} 0%, ${theme.bgMid} 48%, ${theme.bgEnd} 100%)`,
        color: "#EBECF1",
        fontFamily: OG_FONT_STACK,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(circle at 18% 16%, ${theme.accentSoft} 0%, transparent 34%), radial-gradient(circle at 84% 18%, rgba(60, 108, 148, 0.24) 0%, transparent 38%)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 24,
          borderRadius: 28,
          border: `2px solid ${theme.frame}`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 72,
          top: 92,
          width: 420,
          height: 16,
          borderRadius: 8,
          background: "rgba(235, 236, 241, 0.06)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 72,
          top: 120,
          width: 302,
          height: 10,
          borderRadius: 5,
          background: "rgba(235, 236, 241, 0.05)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: "71.5%",
          top: 74,
          bottom: 74,
          width: 3,
          background: theme.line,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: "65%",
          top: "50%",
          width: 168,
          height: 168,
          borderRadius: 999,
          border: `3px solid ${theme.line}`,
          transform: "translate(-50%, -50%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          right: 86,
          top: 170,
          width: 180,
          height: 212,
          border: `3px solid ${theme.line}`,
          borderRight: "0",
          borderRadius: "26px 0 0 26px",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 122,
          bottom: 138,
          width: 430,
          borderTop: `4px dashed ${theme.accent}`,
          transform: "rotate(-8deg)",
          opacity: 0.8,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 602,
          top: 162,
          width: 276,
          borderTop: `4px dashed ${theme.secondary}`,
          transform: "rotate(12deg)",
          opacity: 0.62,
        }}
      />
      <div
        style={{
          display: "flex",
          width: "100%",
          height: "100%",
          padding: "56px 64px",
          justifyContent: "space-between",
          gap: 28,
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            width: "63%",
            justifyContent: "space-between",
            paddingTop: 44,
            paddingBottom: 10,
          }}
        >
          <div
            style={{
              display: "flex",
              gap: 16,
              alignItems: "center",
            }}
          >
            <div
              style={{
                fontSize: 24,
                fontWeight: 700,
                letterSpacing: "-0.03em",
                color: "#EBECF1",
              }}
            >
              {siteName}
            </div>
            <div
              style={{
                fontSize: 14,
                fontWeight: 600,
                letterSpacing: "0.2em",
                textTransform: "uppercase",
                color: theme.accent,
                border: `1px solid ${theme.accentSoft}`,
                padding: "6px 12px",
                borderRadius: 999,
                background: "rgba(8, 19, 31, 0.42)",
              }}
            >
              {section.label}
            </div>
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              maxWidth: 760,
            }}
          >
            <div
              style={{
                fontSize: 18,
                fontWeight: 700,
                letterSpacing: "0.24em",
                textTransform: "uppercase",
                color: theme.accent,
              }}
            >
              {section.eyebrow}
            </div>
            <div
              style={{
                marginTop: 20,
                fontSize: titleSize,
                fontWeight: 700,
                lineHeight: 0.96,
                letterSpacing: "-0.05em",
                color: "#EBECF1",
              }}
            >
              {title}
            </div>
            {description ? (
              <div
                style={{
                  marginTop: 26,
                  fontSize: 28,
                  lineHeight: 1.35,
                  color: "rgba(235, 236, 241, 0.78)",
                  maxWidth: 720,
                }}
              >
                {description}
              </div>
            ) : null}
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            {footerItems.map((item) => (
              <div
                key={item}
                style={{
                  display: "flex",
                  alignItems: "center",
                  borderRadius: 999,
                  border: "1px solid rgba(235, 236, 241, 0.14)",
                  background: "rgba(8, 19, 31, 0.54)",
                  padding: "10px 18px",
                  fontSize: 16,
                  fontWeight: 600,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "rgba(235, 236, 241, 0.84)",
                }}
              >
                {item}
              </div>
            ))}
          </div>
        </div>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            width: "31%",
            paddingTop: 44,
            paddingBottom: 8,
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 14,
              borderRadius: 28,
              border: `1px solid ${theme.frame}`,
              background: theme.panel,
              padding: "24px 24px 22px",
            }}
          >
            <div
              style={{
                fontSize: 14,
                fontWeight: 600,
                letterSpacing: "0.22em",
                textTransform: "uppercase",
                color: theme.accent,
              }}
            >
              {section.cue}
            </div>
            <div
              style={{
                fontSize: 38,
                fontWeight: 700,
                lineHeight: 1.02,
                color: "#EBECF1",
              }}
            >
              {section.label}
            </div>
            <div
              style={{
                fontSize: 18,
                lineHeight: 1.45,
                color: "rgba(235, 236, 241, 0.72)",
              }}
            >
              {section.blurb}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {sectionStats.map((stat) => (
              <div
                key={stat.label}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  borderRadius: 24,
                  border: "1px solid rgba(235, 236, 241, 0.12)",
                  background: "rgba(8, 19, 31, 0.58)",
                  padding: "18px 20px",
                }}
              >
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    letterSpacing: "0.18em",
                    textTransform: "uppercase",
                    color: theme.accent,
                  }}
                >
                  {stat.label}
                </div>
                <div
                  style={{
                    marginTop: 8,
                    fontSize: 23,
                    fontWeight: 600,
                    lineHeight: 1.18,
                    color: "#EBECF1",
                  }}
                >
                  {stat.value}
                </div>
              </div>
            ))}
          </div>
          <div
            style={{
              borderRadius: 24,
              border: "1px solid rgba(235, 236, 241, 0.12)",
              background: "rgba(8, 19, 31, 0.52)",
              padding: "16px 20px",
              fontSize: 16,
              lineHeight: 1.45,
              color: "rgba(235, 236, 241, 0.72)",
            }}
          >
            Built for warehouse readers who want the court view, not generic
            docs chrome.
          </div>
        </div>
      </div>
    </div>,
    {
      width: 1200,
      height: 630,
      headers: {
        "Cache-Control":
          "public, max-age=86400, s-maxage=604800, stale-while-revalidate=86400",
      },
    },
  );
}
