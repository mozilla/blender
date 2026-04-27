.PHONY: lint lint-shell lint-actions lint-zizmor lint-python lint-yaml fmt

lint: lint-shell lint-actions lint-zizmor lint-python lint-yaml

lint-shell:
	shellcheck scripts/*.sh

lint-actions:
	actionlint

lint-zizmor:
	zizmor .github/workflows/

lint-python:
	uv run ruff check scripts/
	uv run ruff format --check scripts/

lint-yaml:
	yamllint -c .yamllint.yml .github/workflows/

fmt:
	uv run ruff format scripts/
