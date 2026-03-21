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
          position: "relative",
          overflow: "hidden",
          background: "linear-gradient(140deg, #fbf6ec 0%, #f2ebdd 42%, #f7efe5 100%)",
          color: "#181e2d",
          fontFamily: "Arial",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage:
              "linear-gradient(rgba(27, 42, 92, 0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(27, 42, 92, 0.08) 1px, transparent 1px)",
            backgroundSize: "88px 88px",
            opacity: 0.55,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: -120,
            left: 760,
            width: 420,
            height: 420,
            borderRadius: 999,
            background: "radial-gradient(circle, rgba(200, 49, 44, 0.22), transparent 68%)",
          }}
        />
        <div
          style={{
            position: "absolute",
            bottom: -148,
            left: 720,
            width: 460,
            height: 280,
            borderTopLeftRadius: 240,
            borderTopRightRadius: 240,
            border: "3px solid rgba(200, 49, 44, 0.22)",
            borderBottom: "0",
          }}
        />
        <div
          style={{
            position: "absolute",
            top: 164,
            left: 865,
            width: 170,
            height: 215,
            border: "2px solid rgba(27, 42, 92, 0.18)",
            borderTopLeftRadius: 26,
            borderTopRightRadius: 26,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: 146,
            left: 934,
            width: 32,
            height: 32,
            borderRadius: 999,
            border: "4px solid rgba(242, 167, 38, 0.78)",
            boxShadow: "0 0 0 12px rgba(242, 167, 38, 0.12)",
          }}
        />

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            width: "100%",
            padding: "58px 64px",
          }}
        >
          <div style={{ display: "flex", gap: 16 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                borderRadius: 999,
                border: "1px solid rgba(200, 49, 44, 0.2)",
                background: "rgba(200, 49, 44, 0.1)",
                padding: "10px 18px",
                fontSize: 24,
                fontWeight: 700,
                letterSpacing: "0.26em",
                textTransform: "uppercase",
              }}
            >
              {section.label}
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                borderRadius: 999,
                border: "1px solid rgba(27, 42, 92, 0.14)",
                background: "rgba(255, 255, 255, 0.7)",
                padding: "10px 18px",
                fontSize: 24,
                fontWeight: 700,
                letterSpacing: "0.2em",
                textTransform: "uppercase",
              }}
            >
              {section.cue}
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", maxWidth: 720 }}>
            <div
              style={{
                fontSize: 80,
                fontWeight: 800,
                lineHeight: 0.95,
                letterSpacing: "-0.06em",
              }}
            >
              {title}
            </div>
            <div
              style={{
                marginTop: 28,
                fontSize: 30,
                lineHeight: 1.35,
                color: "rgba(24, 30, 45, 0.72)",
              }}
            >
              {description}
            </div>
          </div>

          <div style={{ display: "flex", gap: 18, alignItems: "center" }}>
            {[siteName, section.eyebrow, "OpenGraph ready"].map((item) => (
              <div
                key={item}
                style={{
                  display: "flex",
                  alignItems: "center",
                  borderRadius: 999,
                  border: "1px solid rgba(27, 42, 92, 0.12)",
                  background: "rgba(255, 255, 255, 0.72)",
                  padding: "10px 18px",
                  fontSize: 22,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
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