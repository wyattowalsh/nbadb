"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, -apple-system, sans-serif",
          backgroundColor: "#1a1a1a",
          color: "#e5e5e5",
        }}
      >
        <div style={{ maxWidth: 420, padding: 24, textAlign: "center" }}>
          <h1
            style={{
              fontSize: 28,
              fontWeight: 700,
              letterSpacing: "-0.02em",
              margin: "0 0 12px",
            }}
          >
            Something went wrong
          </h1>

          <p
            style={{
              fontSize: 14,
              lineHeight: 1.6,
              color: "#a3a3a3",
              margin: "0 0 8px",
            }}
          >
            A critical error prevented the page from loading.
          </p>

          {error.digest && (
            <p
              style={{
                fontSize: 12,
                fontFamily: "monospace",
                color: "#737373",
                margin: "0 0 24px",
              }}
            >
              Error ID: {error.digest}
            </p>
          )}

          <button
            onClick={reset}
            type="button"
            style={{
              appearance: "none",
              border: "1px solid #404040",
              borderRadius: 6,
              backgroundColor: "#262626",
              color: "#e5e5e5",
              padding: "8px 20px",
              fontSize: 14,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
