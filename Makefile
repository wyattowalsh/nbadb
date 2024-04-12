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

tests: ## runs tests on the bot package
	echo "Running tests..."
	poetry shell && poetry install
	poetry run pytest tests/

format: ## runs linter on the bot package
	echo "Running formatters..."
	poetry shell && poetry install
	poetry run isort nbadb/ && poetry run isort tests/
	poetry run autoflake --recursive nbadb/ && poetry run autoflake --recursive tests/
	poetry run yapf nbadb/ tests/