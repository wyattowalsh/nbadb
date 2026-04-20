import { source } from "@/lib/source";
import { expandSearchQuery } from "@/lib/search-query";
import { createFromSource } from "fumadocs-core/search/server";

const searchHandler = createFromSource(source, {
  language: "english",
});

export async function GET(request: Request) {
  const url = new URL(request.url);
  const query = url.searchParams.get("query");

  if (query) {
    url.searchParams.set("query", expandSearchQuery(query));
  }

  return searchHandler.GET(new Request(url.toString(), request));
}
