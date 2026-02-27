# nbadb

[![PyPI](https://img.shields.io/pypi/v/nbadb)](https://pypi.org/project/nbadb/)
[![Python](https://img.shields.io/pypi/pyversions/nbadb)](https://pypi.org/project/nbadb/)
[![License](https://img.shields.io/github/license/wyattowalsh/nbadb)](LICENSE)
[![Kaggle](https://img.shields.io/badge/Kaggle-Dataset-blue?logo=kaggle)](https://www.kaggle.com/datasets/wyattowalsh/basketball)

Comprehensive NBA database: **131 endpoints** from [nba_api](https://github.com/swar/nba_api) normalized into a **star schema** with 13 dimensions, 20 facts, 2 bridges, 15 derived aggregations, and 4 analytics views (~58 tables).

## Outputs

| Format | Description |
|--------|-------------|
| SQLite | Portable single-file database |
| DuckDB | Columnar analytics engine |
| Parquet | Compressed columnar files (zstd, partitioned by season) |
| CSV | Universal flat files |

## Quick Start

```bash
pip install nbadb

# Full build from scratch
nbadb init

# Daily incremental update
nbadb daily

# Export to all formats
nbadb export

# Upload to Kaggle
nbadb upload
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `nbadb init` | Full rebuild (~2-4h) |
| `nbadb daily` | Incremental update (~5-15m) |
| `nbadb monthly` | Dimension refresh (~30-60m) |
| `nbadb full` | Fill gaps, preserve existing |
| `nbadb export` | Re-export to all formats |
| `nbadb upload` | Push to Kaggle |
| `nbadb download` | Pull from Kaggle |
| `nbadb schema list` | List all table schemas |
| `nbadb status` | DB stats and freshness |

## Tech Stack

| Component | Technology |
|-----------|------------|
| DataFrames | Polars 1.38 |
| Validation | Pandera (Polars) |
| SQLite ORM | SQLModel |
| Analytics DB | DuckDB 1.4 |
| HTTP/Proxy | proxywhirl |
| CLI | Typer + Rich |
| Docs | [nbadb.w4w.dev](https://nbadb.w4w.dev) |

## Documentation

Full documentation at **[nbadb.w4w.dev](https://nbadb.w4w.dev)** including:

- Star schema reference and ER diagrams
- Field-level data dictionary
- Column-level lineage
- DuckDB query cookbook
- Parquet usage guides

## License

MIT
