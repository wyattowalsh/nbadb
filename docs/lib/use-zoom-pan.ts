"use client";

import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  type CSSProperties,
  type RefCallback,
} from "react";

interface ZoomPanState {
  scale: number;
  tx: number;
  ty: number;
}

type Action =
  | { type: "ZOOM"; cx: number; cy: number; delta: number }
  | { type: "PAN"; dx: number; dy: number }
  | { type: "SET"; scale: number; tx: number; ty: number }
  | { type: "RESET" };

const MIN_SCALE = 0.1;
const MAX_SCALE = 20;
const SCROLL_FACTOR = 1.08;
const BUTTON_FACTOR = 1.25;
const PAN_STEP = 50;

const INITIAL: ZoomPanState = { scale: 1, tx: 0, ty: 0 };

function clampScale(s: number) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));
}

function reducer(state: ZoomPanState, action: Action): ZoomPanState {
  switch (action.type) {
    case "ZOOM": {
      const { cx, cy, delta } = action;
      const factor = delta > 0 ? 1 / SCROLL_FACTOR : SCROLL_FACTOR;
      const next = clampScale(state.scale * factor);
      if (next === state.scale) return state;
      const ratio = next / state.scale;
      return {
        scale: next,
        tx: cx - (cx - state.tx) * ratio,
        ty: cy - (cy - state.ty) * ratio,
      };
    }
    case "PAN":
      return { ...state, tx: state.tx + action.dx, ty: state.ty + action.dy };
    case "SET":
      return {
        scale: clampScale(action.scale),
        tx: action.tx,
        ty: action.ty,
      };
    case "RESET":
      return INITIAL;
    default:
      return state;
  }
}

export function useZoomPan() {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const [viewportEl, setViewportEl] = useState<HTMLElement | null>(null);
  const canvasElRef = useRef<HTMLElement | null>(null);
  const pointerRef = useRef<{ id: number; x: number; y: number } | null>(null);
  const touchRef = useRef<{ t1: Touch; t2: Touch; dist: number } | null>(null);

  // Imperative wheel handler — must be non-passive to preventDefault
  useEffect(() => {
    if (!viewportEl) return;

    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const rect = viewportEl!.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      dispatch({ type: "ZOOM", cx, cy, delta: e.deltaY });
    }

    viewportEl.addEventListener("wheel", onWheel, { passive: false });
    return () => viewportEl.removeEventListener("wheel", onWheel);
  }, [viewportEl]);

  // Touch pinch-to-zoom and two-finger pan
  useEffect(() => {
    if (!viewportEl) return;

    function touchDist(a: Touch, b: Touch) {
      const dx = a.clientX - b.clientX;
      const dy = a.clientY - b.clientY;
      return Math.sqrt(dx * dx + dy * dy);
    }

    function touchCenter(a: Touch, b: Touch, rect: DOMRect) {
      return {
        cx: (a.clientX + b.clientX) / 2 - rect.left,
        cy: (a.clientY + b.clientY) / 2 - rect.top,
      };
    }

    function onTouchStart(e: TouchEvent) {
      if (e.touches.length === 2) {
        e.preventDefault();
        const t1 = e.touches[0];
        const t2 = e.touches[1];
        touchRef.current = { t1, t2, dist: touchDist(t1, t2) };
      }
    }

    function onTouchMove(e: TouchEvent) {
      if (e.touches.length === 2 && touchRef.current) {
        e.preventDefault();
        const t1 = e.touches[0];
        const t2 = e.touches[1];
        const newDist = touchDist(t1, t2);
        const oldDist = touchRef.current.dist;

        if (oldDist > 0) {
          const rect = viewportEl!.getBoundingClientRect();
          const { cx, cy } = touchCenter(t1, t2, rect);

          // Simulate zoom: negative delta zooms in (fingers apart), positive zooms out
          const delta = oldDist > newDist ? 1 : -1;
          const scaleFactor = Math.abs(newDist - oldDist) / oldDist;

          // Only zoom if the pinch movement is significant enough
          if (scaleFactor > 0.01) {
            dispatch({ type: "ZOOM", cx, cy, delta });
          }

          // Two-finger pan: track midpoint movement
          const oldCenter = touchCenter(touchRef.current.t1, touchRef.current.t2, rect);
          const newCenter = touchCenter(t1, t2, rect);
          const dx = newCenter.cx - oldCenter.cx;
          const dy = newCenter.cy - oldCenter.cy;
          if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
            dispatch({ type: "PAN", dx, dy });
          }
        }

        touchRef.current = { t1, t2, dist: newDist };
      }
    }

    function onTouchEnd() {
      touchRef.current = null;
    }

    viewportEl.addEventListener("touchstart", onTouchStart, { passive: false });
    viewportEl.addEventListener("touchmove", onTouchMove, { passive: false });
    viewportEl.addEventListener("touchend", onTouchEnd);
    viewportEl.addEventListener("touchcancel", onTouchEnd);

    return () => {
      viewportEl.removeEventListener("touchstart", onTouchStart);
      viewportEl.removeEventListener("touchmove", onTouchMove);
      viewportEl.removeEventListener("touchend", onTouchEnd);
      viewportEl.removeEventListener("touchcancel", onTouchEnd);
    };
  }, [viewportEl]);

  const viewportRef: RefCallback<HTMLElement> = useCallback((node) => {
    setViewportEl(node);
  }, []);

  const setCanvasRef: RefCallback<HTMLElement> = useCallback((node) => {
    canvasElRef.current = node;
  }, []);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0) return;
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      pointerRef.current = { id: e.pointerId, x: e.clientX, y: e.clientY };
    },
    [],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      const p = pointerRef.current;
      if (!p || p.id !== e.pointerId) return;
      const dx = e.clientX - p.x;
      const dy = e.clientY - p.y;
      p.x = e.clientX;
      p.y = e.clientY;
      dispatch({ type: "PAN", dx, dy });
    },
    [],
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent) => {
      if (pointerRef.current?.id === e.pointerId) {
        pointerRef.current = null;
      }
    },
    [],
  );

  const fitToView = useCallback(() => {
    const canvas = canvasElRef.current;
    if (!viewportEl || !canvas) return;

    const vpW = viewportEl.clientWidth;
    const vpH = viewportEl.clientHeight;
    const contentW = canvas.scrollWidth;
    const contentH = canvas.scrollHeight;

    if (contentW === 0 || contentH === 0) {
      dispatch({ type: "RESET" });
      return;
    }

    const fitScale = Math.min(vpW / contentW, vpH / contentH, 1);
    const tx = (vpW - contentW * fitScale) / 2;
    const ty = (vpH - contentH * fitScale) / 2;
    dispatch({ type: "SET", scale: fitScale, tx, ty });
  }, [viewportEl]);

  const zoomAt = useCallback(
    (factor: number) => {
      if (!viewportEl) return;
      const rect = viewportEl.getBoundingClientRect();
      const cx = rect.width / 2;
      const cy = rect.height / 2;
      const next = clampScale(state.scale * factor);
      if (next === state.scale) return;
      const ratio = next / state.scale;
      dispatch({
        type: "SET",
        scale: next,
        tx: cx - (cx - state.tx) * ratio,
        ty: cy - (cy - state.ty) * ratio,
      });
    },
    [viewportEl, state.scale, state.tx, state.ty],
  );

  const zoomIn = useCallback(() => zoomAt(BUTTON_FACTOR), [zoomAt]);
  const zoomOut = useCallback(() => zoomAt(1 / BUTTON_FACTOR), [zoomAt]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      switch (e.key) {
        case "+":
        case "=":
          e.preventDefault();
          zoomIn();
          break;
        case "-":
          e.preventDefault();
          zoomOut();
          break;
        case "0":
          e.preventDefault();
          fitToView();
          break;
        case "ArrowUp":
          e.preventDefault();
          dispatch({ type: "PAN", dx: 0, dy: PAN_STEP });
          break;
        case "ArrowDown":
          e.preventDefault();
          dispatch({ type: "PAN", dx: 0, dy: -PAN_STEP });
          break;
        case "ArrowLeft":
          e.preventDefault();
          dispatch({ type: "PAN", dx: PAN_STEP, dy: 0 });
          break;
        case "ArrowRight":
          e.preventDefault();
          dispatch({ type: "PAN", dx: -PAN_STEP, dy: 0 });
          break;
        case "Home":
          e.preventDefault();
          fitToView();
          break;
      }
    },
    [zoomIn, zoomOut, fitToView],
  );

  const canvasStyle: CSSProperties = {
    transform: `translate(${state.tx}px, ${state.ty}px) scale(${state.scale})`,
    transformOrigin: "0 0",
    willChange: "transform",
    // Allow single-finger pan to scroll the page; two-finger gestures are
    // handled by the imperative touch handlers for pinch-to-zoom.
    touchAction: "pan-x pan-y",
  };

  const pct = Math.round(state.scale * 100);

  return {
    state,
    viewportRef,
    canvasRef: setCanvasRef,
    canvasStyle,
    zoomIn,
    zoomOut,
    resetView: fitToView,
    fitToView,
    pct,
    pointerHandlers: { onPointerDown, onPointerMove, onPointerUp },
    onKeyDown,
  };
}
