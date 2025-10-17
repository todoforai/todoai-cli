.PHONY: help clean build test deploy deploy-patch deploy-minor deploy-major dry-run install dev-install

# Default target
help:
	@echo "Available commands:"
	@echo "  make install      - Install package"
	@echo "  make dev-install  - Install in development mode"
	@echo "  make test         - Run tests"
	@echo "  make clean        - Clean build artifacts"
	@echo "  make build        - Build package"
	@echo "  make dry-run      - Show what deployment would do"
	@echo "  make deploy       - Deploy with patch version bump"
	@echo "  make deploy-patch - Deploy with patch version bump (0.1.1 -> 0.1.2)"
	@echo "  make deploy-minor - Deploy with minor version bump (0.1.1 -> 0.2.0)"
	@echo "  make deploy-major - Deploy with major version bump (0.1.1 -> 1.0.0)"

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

deploy: deploy-patch

deploy-patch:
	python -m todoai_cli.deploy --bump patch

deploy-minor:
	python -m todoai_cli.deploy --bump minor

deploy-major:
	python -m todoai_cli.deploy --bump major

# Quick test and deploy
test-deploy: test deploy-patch