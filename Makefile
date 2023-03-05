# nba_db project Makefile

.ONESHELL:

# https://www.gnu.org/prep/standards/html_node/Makefile-Basics.html#Makefile-Basics
SHELL = /bin/bash

help:           ## Show this help.
	fgrep -h "##" $(MAKEFILE_LIST) | fgrep -v fgrep | sed -e 's/\\$$//' | sed -e 's/##//'

jupyter lab:  ## launch jupyter lab from project root
	echo "Starting Jupyter Lab..."
	poetry shell && poetry install
	poetry run jupyter lab

docs build html:  ## build docs as html
	echo "Building docs..."
	poetry shell && poetry install
	cd docs && poetry run make html
	echo "Docs built in docs/html"

docs server: ## launch docs server
	echo "Starting docs server..."
	poetry shell && poetry install
	poetry run sphinx-autobuild docs docs/_build/html --port 7777 --open-browser

tests: ## runs tests on the bot package
	echo "Running tests..."
	poetry shell && poetry install
	poetry run pytest tests/

format: ## runs linter on the bot package
	echo "Running formatters..."
	poetry shell && poetry install
	poetry run isort nba_db/ && poetry run isort tests/
	poetry run autoflake --recursive nba_db/ && poetry run autoflake --recursive tests/
	poetry run black nba_db/ tests/

create requirements file: ## creates requirements.txt file
	echo "Creating requirements.txt file..."
	poetry shell && poetry install
	poetry run pipreqs --savepath ./requirements.txt nba_db