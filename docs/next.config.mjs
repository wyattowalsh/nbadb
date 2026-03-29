import { fileURLToPath } from "node:url";
import { createMDX } from "fumadocs-mdx/next";

const withMDX = createMDX();
const docsRoot = fileURLToPath(new URL("./", import.meta.url));

/** @type {import('next').NextConfig} */
const config = {
  turbopack: {
    root: docsRoot,
  },
};

export default withMDX(config);
