(usage)=

# Usage

This project makes use of a `Makefile` to automate popular workflows. So far, the following workflows exist:

- [Launch Jupyter Lab](#launch-jupyter-lab)
- [Build docs as HTML](#build-docs-as-html)
- [Launch docs server](#launch-docs-server)
- [Run tests](#run-tests)
- [Run Formatters](#run-formatters)
- [Create requirements.txt file](#create-requirementstxt-file)

## Launch Jupyter Lab

```{code-block} console
:caption: run the following snippet in the `terminal` app
poetry run make jupyter lab
```

This command will launch Jupyter Lab in your browser. From there, you can interact with project notebooks.

## Build docs as HTML

```{code-block} console
:caption: run the following snippet in the `terminal` app
poetry run make docs build html
```

This command will build the docs site as HTML. The HTML files will be located in the `docs/_build/html` directory.

## Launch docs server

```{code-block} console
:caption: run the following snippet in the `terminal` app
```

This command will launch a local server to view the docs site. The server will be accessible at `http://localhost:7777`.

## Run tests

```{code-block} console
:caption: run the following snippet in the `terminal` app
poetry run make tests
```

This command will run all tests in the `tests` directory using `pytest`.

## Run Formatters

```{code-block} console
:caption: run the following snippet in the `terminal` app
poetry run make format
```

This command will run all formatters including:

- isort
- autoflake
- black

## Create requirements.txt file

```{code-block} console
:caption: run the following snippet in the `terminal` app
poetry run make create requirements file
```

This command will create a `requirements.txt` file in the project root directory using `pipreqs`. This file can be used to install dependencies in a non-poetry environment.
