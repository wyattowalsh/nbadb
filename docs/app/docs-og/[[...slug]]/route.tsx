import { ImageResponse } from "next/og";
import { getSectionMeta, siteName } from "@/lib/site-config";
import { source } from "@/lib/source";

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

  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          width: "100%",
          height: "100%",
          background: "#0a0a0c",
          color: "#e8e8ec",
          fontFamily: "monospace",
          position: "relative",
        }}
      >
        {/* Top border accent */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: 4,
            background: "#f26522",
          }}
        />

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            width: "100%",
            padding: "56px 64px",
          }}
        >
          {/* Header */}
          <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
            <div
              style={{
                fontSize: 28,
                fontWeight: 700,
                letterSpacing: "-0.03em",
                color: "#e8e8ec",
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
                color: "#f26522",
                border: "1px solid rgba(242, 101, 34, 0.3)",
                padding: "6px 12px",
              }}
            >
              {section.label}
            </div>
          </div>

          {/* Title + description */}
          <div style={{ display: "flex", flexDirection: "column", maxWidth: 900 }}>
            <div
              style={{
                fontSize: 72,
                fontWeight: 700,
                lineHeight: 1,
                letterSpacing: "-0.04em",
                color: "#e8e8ec",
              }}
            >
              {title}
            </div>
            {description ? (
              <div
                style={{
                  marginTop: 24,
                  fontSize: 26,
                  lineHeight: 1.4,
                  color: "#888890",
                }}
              >
                {description}
              </div>
            ) : null}
          </div>

          {/* Footer stats */}
          <div style={{ display: "flex", gap: 24, alignItems: "center" }}>
            {["141 tables", "131 endpoints", "DuckDB"].map((item) => (
              <div
                key={item}
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  letterSpacing: "0.16em",
                  textTransform: "uppercase",
                  color: "#888890",
                  border: "1px solid #2a2a30",
                  padding: "8px 14px",
                }}
              >
                {item}
              </div>
            ))}
          </div>
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
    },
  );
}
