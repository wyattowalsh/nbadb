CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    record_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trajectories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    archetype TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_trajectories_created_at
    ON trajectories(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_trajectories_archetype
    ON trajectories(archetype);