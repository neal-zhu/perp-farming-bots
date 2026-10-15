.PHONY: run test check docs-check

run:
	uv run perp-farming-bots

test:
	uv run pytest -q

check:
	uv run ruff check src tests scripts
	uv run mypy
	$(MAKE) docs-check

docs-check:
	uv run python scripts/check_docs.py
	uv run python scripts/export_account_guide.py --check
