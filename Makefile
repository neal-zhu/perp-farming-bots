.PHONY: run test check

run:
	uv run perp-farming-bots

test:
	uv run pytest -q

check:
	uv run ruff check src tests
	uv run mypy
