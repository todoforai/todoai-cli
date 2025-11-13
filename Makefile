.PHONY: help clean build test deploy deploy-patch deploy-minor deploy-major dry-run install dev-install release tag-release

# Default target
help:
	@echo "Available commands:"
	@echo "  make install      - Install package"
	@echo "  make dev-install  - Install in development mode"
	@echo "  make test         - Run tests"
	@echo "  make clean        - Clean build artifacts"
	@echo "  make build        - Build package"
	@echo "  make dry-run      - Show what deployment would do"
	@echo "  make deploy       - Deploy with patch version bump (local)"
	@echo "  make deploy-patch - Deploy with patch version bump (local)"
	@echo "  make deploy-minor - Deploy with minor version bump (local)"
	@echo "  make deploy-major - Deploy with major version bump (local)"
	@echo "  make release      - Trigger GitHub Actions release (recommended)"

install:
	pip install .

dev-install:
	pip install -e .
	pip install build twine pytest

test:
	python -m pytest

clean:
	rm -rf build/ dist/ *.egg-info/ __pycache__/ .pytest_cache/
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} +

build: clean
	python -m build

dry-run:
	python -m todoai_cli.deploy --dry-run

# Local deployment (not recommended for production)
deploy: deploy-patch

deploy-patch:
	python -m todoai_cli.deploy --bump patch

deploy-minor:
	python -m todoai_cli.deploy --bump minor

deploy-major:
	python -m todoai_cli.deploy --bump major

# Recommended: Use GitHub Actions for releases
release:
	@echo "🚀 Triggering GitHub Actions release..."
	@echo "Go to: https://github.com/todoforai/todoai-cli/actions/workflows/release.yml"
	@echo "Click 'Run workflow' and select version bump type"

# Quick test and deploy
test-deploy: test deploy-patch
