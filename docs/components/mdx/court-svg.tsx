"use client";

/**
 * Pure SVG half-court diagram for compositing behind shot chart dot plots.
 *
 * Coordinate system matches nba_api shot chart data:
 *   x: -250 to 250, y: -47.5 to 420
 *   Hoop at (0, 0), baseline at y = -47.5, half-court at y = 420.
 */
export function CourtSvg({
  color,
  lineWidth = 1.5,
  className,
}: {
  /** Stroke color. Defaults to a subtle blend of currentColor. */
  color?: string;
  /** Stroke width for all court lines. @default 1.5 */
  lineWidth?: number;
  /** Additional CSS classes on the root <svg>. */
  className?: string;
}) {
  const stroke =
    color ?? "color-mix(in oklch, currentColor 20%, transparent)";

  return (
    <svg
      viewBox="-250 -47.5 500 470"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      style={{ width: "100%", height: "auto" }}
    >
      <g fill="none" stroke={stroke} strokeWidth={lineWidth}>
        {/* Court outline */}
        <rect x={-250} y={-47.5} width={500} height={467.5} />

        {/* Half-court line */}
        <line x1={-250} y1={420} x2={250} y2={420} />

        {/* Center court half-circle (upper half at y=420) */}
        <path d="M -60,420 A 60,60 0 0,0 60,420" />

        {/* Paint / key */}
        <rect x={-80} y={-47.5} width={160} height={190} />

        {/* Free throw circle — upper half (solid) */}
        <path d="M -60,142.5 A 60,60 0 0,1 60,142.5" />

        {/* Free throw circle — lower half (dashed) */}
        <path
          d="M -60,142.5 A 60,60 0 0,0 60,142.5"
          strokeDasharray="4 4"
        />

        {/* Backboard */}
        <line x1={-30} y1={-7.5} x2={30} y2={-7.5} />

        {/* Hoop */}
        <circle cx={0} cy={0} r={7.5} />

        {/* Restricted area arc */}
        <path d="M -40,0 A 40,40 0 0,1 40,0" />

        {/* Three-point arc */}
        <path d="M 220.2,89.0 A 237.5,237.5 0 0,1 -220.2,89.0" />

        {/* Corner three — right */}
        <line x1={220} y1={-47.5} x2={220} y2={89} />

        {/* Corner three — left */}
        <line x1={-220} y1={-47.5} x2={-220} y2={89} />
      </g>
    </svg>
  );
}
