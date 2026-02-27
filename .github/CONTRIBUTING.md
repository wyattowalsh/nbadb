# Contributing to nbadb

## Setup

```bash
git clone https://github.com/wyattowalsh/nbadb.git
cd nbadb
uv sync --extra dev
```

## Development

```bash
make lint        # ruff check + format
make typecheck   # ty check
make test        # pytest unit tests
make test-all    # all tests
```

## Guidelines

- Use Polars (not pandas) for all DataFrame operations
- Validate with Pandera: `import pandera.polars as pa`
- Write to SQLite via ADBC: `df.write_database(..., engine="adbc")`
- DuckDB uses native Python API only
- All column names lowercase
- Type annotate everything; run `ty check`

## Pull Requests

1. Fork and create a feature branch
2. Make changes with tests
3. Run `make lint && make typecheck && make test`
4. Submit PR against `main`
