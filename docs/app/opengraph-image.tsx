import { ImageResponse } from "next/og";
import { siteDescription, siteTitle } from "@/lib/site-config";

export const size = {
  width: 1200,
  height: 630,
};

export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          height: "100%",
          width: "100%",
          background:
            "linear-gradient(135deg, #fbf6ec 0%, #f2ebdd 42%, #f7efe5 100%)",
          color: "#181e2d",
          fontFamily: "Arial",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage:
              "linear-gradient(rgba(27, 42, 92, 0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(27, 42, 92, 0.08) 1px, transparent 1px)",
            backgroundSize: "80px 80px",
            opacity: 0.6,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: -140,
            right: -90,
            width: 420,
            height: 420,
            borderRadius: 999,
            background: "radial-gradient(circle, rgba(200, 49, 44, 0.22), transparent 68%)",
          }}
        />
        <div
          style={{
            position: "absolute",
            bottom: -150,
            left: 730,
            width: 520,
            height: 300,
            borderTopLeftRadius: 260,
            borderTopRightRadius: 260,
            border: "3px solid rgba(200, 49, 44, 0.24)",
            borderBottom: "0",
          }}
        />
        <div
          style={{
            position: "absolute",
            top: 160,
            left: 842,
            width: 180,
            height: 230,
            border: "2px solid rgba(27, 42, 92, 0.18)",
            borderTopLeftRadius: 28,
            borderTopRightRadius: 28,
          }}
        />
        <div
          style={{
            position: "absolute",
            top: 142,
            left: 916,
            width: 34,
            height: 34,
            borderRadius: 999,
            border: "4px solid rgba(242, 167, 38, 0.8)",
            boxShadow: "0 0 0 14px rgba(242, 167, 38, 0.12)",
          }}
        />

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            padding: "58px 64px",
            width: "100%",
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
              Arena Data Lab
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                borderRadius: 999,
                border: "1px solid rgba(27, 42, 92, 0.14)",
                background: "rgba(255, 255, 255, 0.65)",
                padding: "10px 18px",
                fontSize: 24,
                fontWeight: 700,
                letterSpacing: "0.2em",
                textTransform: "uppercase",
              }}
            >
              141 tables
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", maxWidth: 700 }}>
            <div
              style={{
                fontSize: 84,
                fontWeight: 800,
                lineHeight: 0.95,
                letterSpacing: "-0.06em",
              }}
            >
              {siteTitle}
            </div>
            <div
              style={{
                marginTop: 28,
                fontSize: 30,
                lineHeight: 1.35,
                color: "rgba(24, 30, 45, 0.72)",
              }}
            >
              {siteDescription}
            </div>
          </div>

          <div style={{ display: "flex", gap: 18, alignItems: "center" }}>
            {[
              "Schema maps",
              "Endpoint scouting",
              "Lineage replay",
              "Prompt packs",
            ].map((item) => (
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
    size,
  );
}