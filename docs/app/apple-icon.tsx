import { ImageResponse } from "next/og";

export const size = {
  width: 180,
  height: 180,
};

export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          width: "100%",
          height: "100%",
          background: "linear-gradient(135deg, #fbf6ec 0%, #f3ebdd 100%)",
          borderRadius: 42,
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            border: "8px solid rgba(27, 42, 92, 0.16)",
            borderRadius: 42,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: 42,
            top: 36,
            width: 96,
            height: 116,
            border: "8px solid rgba(27, 42, 92, 0.58)",
            borderTopLeftRadius: 24,
            borderTopRightRadius: 24,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: 79,
            top: 31,
            width: 22,
            height: 22,
            borderRadius: 999,
            border: "8px solid rgba(242, 167, 38, 0.94)",
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#c8312c",
            fontSize: 62,
            fontWeight: 800,
            letterSpacing: "-0.08em",
          }}
        >
          nb
        </div>
      </div>
    ),
    size,
  );
}