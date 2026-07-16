import DOMPurify from "dompurify";

const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const XHTML_NAMESPACE = "http://www.w3.org/1999/xhtml";
const XML_NAMED_ENTITIES = new Set(["amp", "apos", "gt", "lt", "quot"]);
const MAX_SVG_SOURCE_LENGTH = 16 * 1024 * 1024;
const MAX_SVG_ELEMENTS = 100_000;
const MAX_PATH_DATA_LENGTH = 4 * 1024 * 1024;
const MAX_VIEWBOX_DIMENSION = 1_000_000;
const MAX_VIEWBOX_ASPECT_RATIO = 10_000;
const MAX_INTRINSIC_DIMENSION = 16_384;

const SAFE_SVG_ELEMENTS = new Set([
  "circle",
  "clippath",
  "defs",
  "desc",
  "ellipse",
  "feblend",
  "fecolormatrix",
  "fecomponenttransfer",
  "fecomposite",
  "feconvolvematrix",
  "fediffuselighting",
  "fedisplacementmap",
  "fedistantlight",
  "fedropshadow",
  "feflood",
  "fefunca",
  "fefuncb",
  "fefuncg",
  "fefuncr",
  "fegaussianblur",
  "femerge",
  "femergenode",
  "femorphology",
  "feoffset",
  "fepointlight",
  "fespecularlighting",
  "fespotlight",
  "fetile",
  "feturbulence",
  "filter",
  "foreignobject",
  "g",
  "line",
  "lineargradient",
  "marker",
  "mask",
  "metadata",
  "path",
  "pattern",
  "polygon",
  "polyline",
  "radialgradient",
  "rect",
  "stop",
  "style",
  "svg",
  "switch",
  "symbol",
  "text",
  "textpath",
  "title",
  "tspan",
  "view",
]);

const SAFE_FOREIGN_LABEL_ELEMENTS = new Set([
  "b",
  "blockquote",
  "br",
  "code",
  "del",
  "div",
  "em",
  "hr",
  "i",
  "kbd",
  "li",
  "mark",
  "ol",
  "p",
  "pre",
  "s",
  "samp",
  "small",
  "span",
  "strong",
  "sub",
  "sup",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "u",
  "ul",
  "var",
  "wbr",
]);

const FORBIDDEN_TAGS = [
  "a",
  "animate",
  "animateMotion",
  "animateTransform",
  "audio",
  "discard",
  "embed",
  "feImage",
  "iframe",
  "image",
  "object",
  "script",
  "set",
  "use",
  "video",
];
const FORBIDDEN_ATTRIBUTES = [
  "attributeName",
  "begin",
  "by",
  "end",
  "formaction",
  "from",
  "href",
  "ping",
  "src",
  "target",
  "to",
  "values",
  "xlink:href",
  "xml:base",
];
const BLOCKED_MUTATION_ATTRIBUTES = new Set(
  FORBIDDEN_ATTRIBUTES.map((attribute) => attribute.toLowerCase()),
);
const UNSAFE_CSS = /(?:@import|expression\s*\(|-moz-binding|behavior\s*:)/i;
const XML_DECLARATION = /<!\s*(?:doctype|entity)|<!\[cdata\[/i;

type HtmlEntityDecoder = (entity: string) => string;

export interface SanitizedMermaidSvg {
  markup: string;
  width: number;
  height: number;
}

function decodeHtmlEntity(entity: string): string {
  const textarea = document.createElement("textarea");
  textarea.innerHTML = entity;
  return textarea.value;
}

function toXmlCharacterReferences(value: string): string {
  return Array.from(
    value,
    (character) => `&#${character.codePointAt(0)};`,
  ).join("");
}

export function normalizeMermaidSvgForXml(
  svg: string,
  decodeEntity: HtmlEntityDecoder = decodeHtmlEntity,
): string {
  const closedBreaks = svg.replace(
    /<br(\s[^<>]*?)?>/gi,
    (tag, attributes: string | undefined) => {
      if (attributes?.trimEnd().endsWith("/")) return tag;
      return `<br${attributes ?? ""} />`;
    },
  );

  return closedBreaks.replace(
    /&([A-Za-z][A-Za-z0-9]+);/g,
    (entity, name: string) => {
      if (XML_NAMED_ENTITIES.has(name)) return entity;
      return toXmlCharacterReferences(decodeEntity(entity));
    },
  );
}

function isInsideForeignObject(element: Element, root: Element): boolean {
  for (
    let parent = element.parentElement;
    parent && parent !== root;
    parent = parent.parentElement
  ) {
    if (
      parent.namespaceURI === SVG_NAMESPACE &&
      parent.localName.toLowerCase() === "foreignobject"
    ) {
      return true;
    }
  }
  return false;
}

function hasUnsafeUrlFunction(value: string): boolean {
  let unsafe = false;
  const remainder = value.replace(/url\s*\(([^)]*)\)/gi, (_match, raw) => {
    const target = String(raw)
      .trim()
      .replace(/^(["'])(.*)\1$/, "$2");
    if (!/^#[A-Za-z_][A-Za-z0-9_.:-]*$/.test(target)) unsafe = true;
    return "";
  });
  return unsafe || /url\s*\(/i.test(remainder);
}

function assertSafeCss(value: string): void {
  if (UNSAFE_CSS.test(value) || hasUnsafeUrlFunction(value)) {
    throw new Error("Mermaid returned unsafe SVG styles");
  }
}

function assertSafeMermaidSvg(root: Element): void {
  const elements = [root, ...root.querySelectorAll("*")];
  if (elements.length > MAX_SVG_ELEMENTS) {
    throw new Error("Mermaid SVG exceeded the element limit");
  }

  for (const element of elements) {
    const localName = element.localName.toLowerCase();
    const isSvgElement = element.namespaceURI === SVG_NAMESPACE;

    if (isSvgElement) {
      if (!SAFE_SVG_ELEMENTS.has(localName)) {
        throw new Error("Mermaid returned unsafe SVG output");
      }
    } else if (
      element.namespaceURI !== XHTML_NAMESPACE ||
      !SAFE_FOREIGN_LABEL_ELEMENTS.has(localName) ||
      !isInsideForeignObject(element, root)
    ) {
      throw new Error("Mermaid returned unsafe foreign content");
    }

    if (localName === "style") {
      assertSafeCss(element.textContent ?? "");
    }

    for (const attribute of element.attributes) {
      const attributeName = attribute.localName.toLowerCase();
      if (
        attributeName.startsWith("on") ||
        BLOCKED_MUTATION_ATTRIBUTES.has(attributeName)
      ) {
        throw new Error("Mermaid returned unsafe SVG attributes");
      }
      if (hasUnsafeUrlFunction(attribute.value)) {
        throw new Error("Mermaid returned an unsafe SVG URL");
      }
      if (attributeName === "style") {
        assertSafeCss(attribute.value);
      }
      if (
        localName === "path" &&
        attributeName === "d" &&
        attribute.value.length > MAX_PATH_DATA_LENGTH
      ) {
        throw new Error("Mermaid SVG path data exceeded the size limit");
      }
    }
  }
}

function setIntrinsicSvgSize(root: Element): { width: number; height: number } {
  root.removeAttribute("width");
  root.removeAttribute("height");
  root.removeAttribute("style");

  const values = root
    .getAttribute("viewBox")
    ?.trim()
    .split(/[\s,]+/)
    .map(Number);
  if (
    !values ||
    values.length !== 4 ||
    !values.every(Number.isFinite) ||
    values[2] <= 0 ||
    values[3] <= 0 ||
    values[2] > MAX_VIEWBOX_DIMENSION ||
    values[3] > MAX_VIEWBOX_DIMENSION ||
    Math.max(values[2] / values[3], values[3] / values[2]) >
      MAX_VIEWBOX_ASPECT_RATIO
  ) {
    throw new Error("Mermaid returned invalid SVG geometry");
  }

  const scale = Math.min(
    1,
    MAX_INTRINSIC_DIMENSION / Math.max(values[2], values[3]),
  );
  const width = Math.max(1, Math.ceil(values[2] * scale));
  const height = Math.max(1, Math.ceil(values[3] * scale));
  root.setAttribute("width", String(width));
  root.setAttribute("height", String(height));
  return { width, height };
}

export function sanitizeMermaidSvg(svg: string): SanitizedMermaidSvg {
  if (svg.length > MAX_SVG_SOURCE_LENGTH) {
    throw new Error("Mermaid SVG exceeded the source size limit");
  }
  if (XML_DECLARATION.test(svg)) {
    throw new Error("Mermaid returned forbidden XML declarations");
  }

  const purified = DOMPurify.sanitize(svg, {
    ADD_ATTR: ["dominant-baseline"],
    ADD_TAGS: ["foreignObject"],
    FORBID_ATTR: FORBIDDEN_ATTRIBUTES,
    FORBID_TAGS: FORBIDDEN_TAGS,
    HTML_INTEGRATION_POINTS: { foreignobject: true },
  });
  const parsed = new DOMParser().parseFromString(
    normalizeMermaidSvgForXml(purified),
    "image/svg+xml",
  );
  const parserError = parsed.querySelector("parsererror");
  const root = parsed.documentElement;
  if (
    parserError ||
    root.namespaceURI !== SVG_NAMESPACE ||
    root.localName.toLowerCase() !== "svg"
  ) {
    throw new Error("Mermaid returned invalid SVG output");
  }

  assertSafeMermaidSvg(root);
  const { width, height } = setIntrinsicSvgSize(root);
  return {
    markup: new XMLSerializer().serializeToString(root),
    width,
    height,
  };
}

export function buildMermaidSandboxDocument(markup: string): string {
  return [
    "<!doctype html>",
    '<html><head><meta http-equiv="Content-Security-Policy"',
    " content=\"default-src 'none'; style-src 'unsafe-inline'; img-src 'none';",
    " font-src 'none'; media-src 'none'; connect-src 'none'; object-src 'none';",
    " base-uri 'none'; form-action 'none'\">",
    "<style>html,body{margin:0;padding:0;background:transparent;overflow:hidden}",
    "svg{display:block}</style></head><body>",
    markup,
    "</body></html>",
  ].join("");
}

export function createMermaidSandboxFrame(
  ownerDocument: Document,
  sanitized: SanitizedMermaidSvg,
): HTMLIFrameElement {
  const frame = ownerDocument.createElement("iframe");
  frame.setAttribute("sandbox", "");
  frame.setAttribute("referrerpolicy", "no-referrer");
  frame.setAttribute("title", "Mermaid diagram");
  frame.setAttribute("aria-label", "Mermaid diagram");
  frame.setAttribute("tabindex", "-1");
  frame.setAttribute("width", String(sanitized.width));
  frame.setAttribute("height", String(sanitized.height));
  frame.style.width = `${sanitized.width}px`;
  frame.style.height = `${sanitized.height}px`;
  frame.style.display = "block";
  frame.style.border = "0";
  frame.style.background = "transparent";
  frame.style.pointerEvents = "none";
  frame.srcdoc = buildMermaidSandboxDocument(sanitized.markup);
  return frame;
}
