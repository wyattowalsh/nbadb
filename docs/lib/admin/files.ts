import { readFile } from "node:fs/promises";

function isMissingFileError(error: unknown): error is NodeJS.ErrnoException {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as NodeJS.ErrnoException).code === "ENOENT"
  );
}

export async function readFirstJson<T>(paths: string[]): Promise<T | null> {
  for (const filePath of paths) {
    try {
      const raw = await readFile(/* turbopackIgnore: true */ filePath, "utf-8");
      return JSON.parse(raw) as T;
    } catch (error) {
      if (isMissingFileError(error)) {
        continue;
      }

      const reason =
        error instanceof Error ? error.message : "Unknown JSON read failure";
      throw new Error(`Failed to load JSON from ${filePath}: ${reason}`, {
        cause: error,
      });
    }
  }

  return null;
}
