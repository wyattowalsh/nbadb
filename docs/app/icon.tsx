import { ImageResponse } from "next/og";

export const size = {
  width: 64,
  height: 64,
};

export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          width: "100%",
          height: "100%",
          background: "linear-gradient(135deg, #fbf6ec 0%, #f3ebdd 100%)",
          borderRadius: 16,
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            border: "4px solid rgba(27, 42, 92, 0.18)",
            borderRadius: 16,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: 14,
            top: 12,
            width: 36,
            height: 46,
            border: "3px solid rgba(27, 42, 92, 0.6)",
            borderTopLeftRadius: 10,
            borderTopRightRadius: 10,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: 27,
            top: 10,
            width: 10,
            height: 10,
            borderRadius: 999,
            border: "3px solid rgba(242, 167, 38, 0.95)",
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
            fontSize: 24,
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