from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from nbadb.cli.app import app
from nbadb.cli.options import DataDirOption  # noqa: TC001

_DEFAULT_OUTPUT = Path("dataset-metadata.json")

OutputOption = Annotated[
    Path,
    typer.Option("--output", "-o", help="Output path for dataset-metadata.json"),
]


@app.command()
def metadata(
    output: OutputOption = _DEFAULT_OUTPUT,
    data_dir: DataDirOption = None,
) -> None:
    """Generate Kaggle dataset-metadata.json from table catalog."""
    from nbadb.kaggle.metadata import generate_metadata

    kwargs: dict[str, Path] = {}
    if data_dir is not None:
        kwargs["data_dir"] = data_dir
    generate_metadata(output, **kwargs)
    typer.echo(f"Generated {output}")
