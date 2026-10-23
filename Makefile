.PHONY: run test lint build

run:
	uv run axonhub

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

build:
	uv build
