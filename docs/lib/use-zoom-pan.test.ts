import { describe, expect, it } from "vitest";

import {
  calculateFitTransform,
  zoomPanReducer,
  type ZoomPanState,
} from "./use-zoom-pan";

const LARGE_DIAGRAMS = [
  { name: "lineage", width: 243, height: 16_384 },
  { name: "pipeline", width: 1_749, height: 5_232 },
  { name: "entity relationship", width: 15_397, height: 3_708 },
] as const;

const VIEWPORTS = [
  { name: "desktop", width: 1_200, height: 720 },
  { name: "mobile", width: 360, height: 480 },
] as const;

describe("calculateFitTransform", () => {
  it.each(LARGE_DIAGRAMS)("contains the large $name diagram", (diagram) => {
    for (const viewport of VIEWPORTS) {
      const transform = calculateFitTransform(
        viewport.width,
        viewport.height,
        diagram.width,
        diagram.height,
      );

      expect(transform, viewport.name).not.toBeNull();
      expect(
        diagram.width * transform!.scale,
        viewport.name,
      ).toBeLessThanOrEqual(viewport.width);
      expect(
        diagram.height * transform!.scale,
        viewport.name,
      ).toBeLessThanOrEqual(viewport.height);
      expect(transform!.tx, viewport.name).toBeGreaterThanOrEqual(0);
      expect(transform!.ty, viewport.name).toBeGreaterThanOrEqual(0);
    }
  });

  it("rejects non-positive and non-finite dimensions", () => {
    expect(calculateFitTransform(0, 480, 100, 100)).toBeNull();
    expect(calculateFitTransform(360, Number.NaN, 100, 100)).toBeNull();
    expect(
      calculateFitTransform(360, 480, Number.POSITIVE_INFINITY, 100),
    ).toBeNull();
  });
});

describe("zoomPanReducer", () => {
  const initial: ZoomPanState = { scale: 1, tx: 0, ty: 0 };

  it("preserves a valid fit scale below the interactive zoom floor", () => {
    const transform = calculateFitTransform(1_200, 720, 15_397, 3_708);

    expect(transform).not.toBeNull();
    expect(transform!.scale).toBeLessThan(0.1);
    expect(zoomPanReducer(initial, { type: "FIT", ...transform! })).toEqual(
      transform,
    );
  });

  it("retains the interactive zoom floor", () => {
    expect(
      zoomPanReducer(initial, {
        type: "SET",
        scale: 0.001,
        tx: 0,
        ty: 0,
      }).scale,
    ).toBe(0.1);
  });

  it("rejects invalid fit transforms", () => {
    expect(
      zoomPanReducer(initial, {
        type: "FIT",
        scale: Number.NaN,
        tx: 0,
        ty: 0,
      }),
    ).toBe(initial);
  });
});
