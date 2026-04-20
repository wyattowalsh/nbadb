import { ImageResponse } from "next/og";
import { docsSections, siteDescription, siteName } from "@/lib/site-config";
import { siteMetrics } from "@/lib/site-metrics.generated";

export const alt = `${siteName} warehouse documentation overview`;
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = "image/png";

const OG_FONT_STACK =
  "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
const metricCards = siteMetrics.slice(0, 4);
const sectionLabels = docsSections.slice(0, 4).map((section) => section.label);

export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        display: "flex",
        height: "100%",
        width: "100%",
        background:
          "radial-gradient(circle at top left, rgba(249, 115, 22, 0.24), transparent 38%), radial-gradient(circle at bottom right, rgba(59, 130, 246, 0.22), transparent 34%), linear-gradient(135deg, #09090b 0%, #111827 48%, #0f172a 100%)",
        color: "#f8fafc",
        fontFamily: OG_FONT_STACK,
        padding: "56px",
        position: "relative",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: "28px",
          border: "1px solid rgba(248, 250, 252, 0.12)",
          borderRadius: "32px",
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: "96px 360px 96px 120px",
          border: "2px solid rgba(249, 115, 22, 0.16)",
          borderRadius: "999px",
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: "56px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "stretch",
          gap: "36px",
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            width: "62%",
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "16px",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "14px",
                fontSize: "24px",
                letterSpacing: "0.28em",
                textTransform: "uppercase",
                color: "#fb923c",
              }}
            >
              <span>NBA warehouse documentation</span>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: "18px",
                flexWrap: "wrap",
              }}
            >
              <span
                style={{
                  fontFamily: OG_FONT_STACK,
                  fontSize: "82px",
                  fontWeight: 700,
                  letterSpacing: "-0.05em",
                  lineHeight: 0.95,
                }}
              >
                {siteName}
              </span>
              <span
                style={{
                  display: "flex",
                  alignItems: "center",
                  border: "1px solid rgba(248, 250, 252, 0.18)",
                  borderRadius: "999px",
                  padding: "10px 18px",
                  fontSize: "24px",
                  color: "#cbd5e1",
                }}
              >
                star schema + DuckDB
              </span>
            </div>
            <div
              style={{
                display: "flex",
                maxWidth: "90%",
                fontSize: "30px",
                lineHeight: 1.35,
                color: "#e2e8f0",
              }}
            >
              {siteDescription}
            </div>
          </div>

          <div
            style={{
              display: "flex",
              gap: "14px",
              flexWrap: "wrap",
            }}
          >
            {sectionLabels.map((label) => (
              <div
                key={label}
                style={{
                  display: "flex",
                  alignItems: "center",
                  borderRadius: "999px",
                  border: "1px solid rgba(248, 250, 252, 0.12)",
                  background: "rgba(15, 23, 42, 0.5)",
                  padding: "10px 16px",
                  fontSize: "20px",
                  color: "#cbd5e1",
                }}
              >
                {label}
              </div>
            ))}
          </div>
        </div>

        <div
          style={{
            display: "flex",
            width: "38%",
            flexDirection: "column",
            justifyContent: "space-between",
            gap: "18px",
          }}
        >
          {metricCards.map((metric) => (
            <div
              key={metric.label}
              style={{
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
                gap: "8px",
                borderRadius: "24px",
                border: "1px solid rgba(248, 250, 252, 0.12)",
                background:
                  "linear-gradient(135deg, rgba(15, 23, 42, 0.86), rgba(17, 24, 39, 0.68))",
                padding: "22px 24px",
                minHeight: "118px",
              }}
            >
              <span
                style={{
                  fontSize: "20px",
                  letterSpacing: "0.2em",
                  textTransform: "uppercase",
                  color: "#fb923c",
                }}
              >
                {metric.label}
              </span>
              <span
                style={{
                  fontFamily: OG_FONT_STACK,
                  fontSize: "48px",
                  fontWeight: 700,
                  letterSpacing: "-0.04em",
                  lineHeight: 1,
                }}
              >
                {metric.value}
              </span>
              <span
                style={{
                  fontSize: "20px",
                  color: "#cbd5e1",
                }}
              >
                {metric.note}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>,
    size,
  );
}
