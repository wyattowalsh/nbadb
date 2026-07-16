// @vitest-environment jsdom

import { describe, expect, it } from "vitest";
import {
  buildMermaidSandboxDocument,
  createMermaidSandboxFrame,
  normalizeMermaidSvgForXml,
  sanitizeMermaidSvg,
} from "@/lib/mermaid-svg";

const ENTITY_VALUES: Record<string, string> = {
  "&copy;": "\u00a9",
  "&nbsp;": "\u00a0",
};

function decodeFixtureEntity(entity: string): string {
  return ENTITY_VALUES[entity] ?? entity;
}

describe("normalizeMermaidSvgForXml", () => {
  it("normalizes Mermaid HTML labels for strict XML parsing", () => {
    const renderedSvg = [
      '<svg xmlns="http://www.w3.org/2000/svg">',
      "<foreignObject>",
      '<div xmlns="http://www.w3.org/1999/xhtml">',
      '<span class="nodeLabel">',
      "<p>Extract&nbsp;&amp;&nbsp;stage<br>Transform &copy;</p>",
      "</span>",
      "</div>",
      "</foreignObject>",
      "</svg>",
    ].join("");

    const normalized = normalizeMermaidSvgForXml(
      renderedSvg,
      decodeFixtureEntity,
    );

    expect(normalized).toContain(
      "<p>Extract&#160;&amp;&#160;stage<br />Transform &#169;</p>",
    );
    expect(normalized).not.toMatch(/&(?:copy|nbsp);|<br>/);
  });

  it("keeps XML-escaped markup encoded", () => {
    const renderedSvg =
      '<svg xmlns="http://www.w3.org/2000/svg"><text>&lt;script onload=&quot;alert(1)&quot;&gt;</text></svg>';

    expect(normalizeMermaidSvgForXml(renderedSvg, decodeFixtureEntity)).toBe(
      renderedSvg,
    );
  });

  it("sanitizes static Mermaid SVG and bounds its intrinsic geometry", () => {
    const sanitized = sanitizeMermaidSvg(
      [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40000 20000">',
        "<style>.node{fill:#fff}</style>",
        '<defs><marker id="arrow"><path d="M0 0L10 5L0 10Z" /></marker></defs>',
        '<path class="node" marker-end="url(#arrow)" d="M0 0L100 100" />',
        '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">',
        "<p>Extract&nbsp;<br>stage</p></div></foreignObject>",
        "</svg>",
      ].join(""),
    );

    expect(sanitized.width).toBe(16384);
    expect(sanitized.height).toBe(8192);
    expect(sanitized.markup).toContain('marker-end="url(#arrow)"');
    expect(sanitized.markup).toContain("<br");
    expect(sanitized.markup).not.toMatch(/<a\b|<script\b|\son\w+=/i);
  });

  it("removes active elements, navigation, and mutation attributes", () => {
    const sanitized = sanitizeMermaidSvg(
      [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">',
        '<a href="javascript:alert(1)"><rect width="10" height="10" /></a>',
        '<animate attributeName="href" values="javascript:alert(2)" />',
        '<image href="https://example.invalid/pixel.png" />',
        '<script>alert(3)</script><rect onload="alert(4)" />',
        "</svg>",
      ].join(""),
    );

    expect(sanitized.markup).not.toMatch(
      /<(?:a|animate|image|script)\b|(?:href|onload|attributeName)=/i,
    );
  });

  it("rejects external CSS resources and malformed geometry", () => {
    expect(() =>
      sanitizeMermaidSvg(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><style>@import url(https://example.invalid/x.css);</style></svg>',
      ),
    ).toThrow(/unsafe SVG styles/);
    expect(() =>
      sanitizeMermaidSvg(
        '<svg xmlns="http://www.w3.org/2000/svg" width="999999999" height="999999999"></svg>',
      ),
    ).toThrow(/invalid SVG geometry/);
    expect(() =>
      sanitizeMermaidSvg(
        '<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>',
      ),
    ).toThrow(/forbidden XML declarations/);
  });

  it("renders only inside a zero-permission CSP sandbox", () => {
    const sanitized = sanitizeMermaidSvg(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><style>#outside{display:none}</style><rect width="100" height="50" /></svg>',
    );
    const frame = createMermaidSandboxFrame(document, sanitized);

    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.style.pointerEvents).toBe("none");
    expect(frame.srcdoc).toBe(buildMermaidSandboxDocument(sanitized.markup));
    expect(frame.srcdoc).toContain("default-src 'none'");
    expect(frame.srcdoc).not.toContain("allow-scripts");
    expect(frame.width).toBe("100");
    expect(frame.height).toBe("50");
  });
});
