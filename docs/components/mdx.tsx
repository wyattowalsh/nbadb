import defaultMdxComponents from "fumadocs-ui/mdx";
import { Mermaid } from "@/components/mdx/mermaid";

export function getMDXComponents(
  components?: Record<string, React.ComponentType>,
) {
  return {
    ...defaultMdxComponents,
    Mermaid,
    ...components,
  };
}
