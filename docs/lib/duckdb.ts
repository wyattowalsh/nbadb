import * as duckdb from "@duckdb/duckdb-wasm";

let dbInstance: duckdb.AsyncDuckDB | null = null;
let initPromise: Promise<duckdb.AsyncDuckDB> | null = null;

/**
 * Get or create a shared DuckDB-WASM instance.
 * Uses jsDelivr CDN bundles — WASM loaded lazily on first call.
 */
export async function getDb(): Promise<duckdb.AsyncDuckDB> {
  if (dbInstance) return dbInstance;
  if (initPromise) return initPromise;

  initPromise = (async () => {
    const JSDELIVR_BUNDLES = duckdb.getJsDelivrBundles();
    const bundle = await duckdb.selectBundle(JSDELIVR_BUNDLES);

    const workerUrl = URL.createObjectURL(
      new Blob([`importScripts("${bundle.mainWorker}");`], {
        type: "text/javascript",
      }),
    );

    const worker = new Worker(workerUrl);
    const logger = new duckdb.ConsoleLogger();
    const db = new duckdb.AsyncDuckDB(logger, worker);

    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    URL.revokeObjectURL(workerUrl);

    dbInstance = db;
    return db;
  })();

  return initPromise;
}

/**
 * Run a SQL query against an in-browser DuckDB instance.
 * Returns results as an array of plain objects.
 */
export async function runQuery(
  sql: string,
): Promise<{ columns: string[]; rows: Record<string, unknown>[] }> {
  const db = await getDb();
  const conn = await db.connect();

  try {
    const result = await conn.query(sql);
    const columns = result.schema.fields.map((f) => f.name);
    const rows = result.toArray().map((row) => {
      const obj: Record<string, unknown> = {};
      for (const col of columns) {
        obj[col] = row[col];
      }
      return obj;
    });
    return { columns, rows };
  } finally {
    await conn.close();
  }
}

/**
 * Register a remote Parquet file with the in-browser DuckDB instance.
 */
export async function registerParquet(
  tableName: string,
  url: string,
): Promise<void> {
  if (!/^[a-z_][a-z0-9_]*$/i.test(tableName)) {
    throw new Error(`Invalid table name: ${tableName}`);
  }
  const safeUrl = url.replace(/'/g, "''");

  const db = await getDb();
  const conn = await db.connect();
  try {
    await conn.query(
      `CREATE OR REPLACE TABLE "${tableName}" AS SELECT * FROM read_parquet('${safeUrl}')`,
    );
  } finally {
    await conn.close();
  }
}

/**
 * Register multiple remote Parquet files, reporting progress.
 */
export async function registerMultipleParquet(
  tables: Array<{ tableName: string; url: string }>,
  onProgress?: (loaded: number, total: number, tableName: string) => void,
): Promise<void> {
  for (let i = 0; i < tables.length; i++) {
    const { tableName, url } = tables[i];
    onProgress?.(i, tables.length, tableName);
    await registerParquet(tableName, url);
  }
  onProgress?.(tables.length, tables.length, "");
}

/**
 * Tear down the shared DuckDB-WASM instance.
 * Call on page navigation to release the Web Worker and memory.
 */
export function destroyDb(): void {
  if (dbInstance) {
    dbInstance.terminate();
    dbInstance = null;
  }
  initPromise = null;
}
