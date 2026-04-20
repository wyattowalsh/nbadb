import * as duckdb from "@duckdb/duckdb-wasm";

let dbInstance: duckdb.AsyncDuckDB | null = null;
let initPromise: Promise<duckdb.AsyncDuckDB> | null = null;
let initGeneration = 0;

type QueryOptions = {
  timeoutMs?: number;
};

/**
 * Get or create a shared DuckDB-WASM instance.
 * Uses jsDelivr CDN bundles — WASM loaded lazily on first call.
 */
export async function getDb(): Promise<duckdb.AsyncDuckDB> {
  if (dbInstance) return dbInstance;
  if (initPromise) return initPromise;

  const pendingGeneration = initGeneration;
  const pendingInit = (async () => {
    const JSDELIVR_BUNDLES = duckdb.getJsDelivrBundles();
    const bundle = await duckdb.selectBundle(JSDELIVR_BUNDLES);

    const workerUrl = URL.createObjectURL(
      new Blob([`importScripts("${bundle.mainWorker}");`], {
        type: "text/javascript",
      }),
    );

    let worker: Worker | null = null;
    let db: duckdb.AsyncDuckDB | null = null;

    try {
      worker = new Worker(workerUrl);
      const logger = new duckdb.ConsoleLogger();
      db = new duckdb.AsyncDuckDB(logger, worker);

      await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
      if (pendingGeneration !== initGeneration) {
        throw new Error(
          "DuckDB initialization was cancelled because the session was reset.",
        );
      }

      dbInstance = db;
      return db;
    } catch (error) {
      if (db) {
        await db.terminate().catch(() => undefined);
      } else {
        worker?.terminate();
      }
      throw error;
    } finally {
      URL.revokeObjectURL(workerUrl);
    }
  })();

  const sharedInit = pendingInit.catch((error) => {
    if (initPromise === sharedInit) {
      initPromise = null;
    }
    throw error;
  });

  initPromise = sharedInit;
  return sharedInit;
}

/**
 * Run a SQL query against an in-browser DuckDB instance.
 * Returns results as an array of plain objects.
 */
export async function runQuery(
  sql: string,
  options: QueryOptions = {},
): Promise<{ columns: string[]; rows: Record<string, unknown>[] }> {
  const db = await getDb();
  const conn = await db.connect();
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let destroyedByTimeout = false;

  try {
    const queryPromise = conn.query(sql);
    const result = options.timeoutMs
      ? await Promise.race([
          queryPromise,
          new Promise<never>((_, reject) => {
            timeoutId = setTimeout(() => {
              destroyedByTimeout = true;
              void destroyDb().then(
                () =>
                  reject(
                    new Error(
                      `Query timed out after ${options.timeoutMs}ms. The in-browser DuckDB session was reset.`,
                    ),
                  ),
                reject,
              );
            }, options.timeoutMs);
          }),
        ])
      : await queryPromise;
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
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
    if (!destroyedByTimeout) {
      await conn.close();
    }
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
export async function destroyDb(): Promise<void> {
  initGeneration += 1;
  initPromise = null;
  if (dbInstance) {
    const current = dbInstance;
    dbInstance = null;
    await current.terminate();
  }
}
