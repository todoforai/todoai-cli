# Contributing to TODOforAI CLI

## Development Setup

1. Clone the repository:
```bash
git clone <repository>
cd todoai-cli
```

2. Install in development mode:
```bash
pip install -e .
```

3. Install development dependencies:
```bash
pip install build twine pytest
```

## Testing

Run tests before deploying:
```bash
python -m pytest
```

## Deployment

We use an automated deployment script that handles version bumping and PyPI publishing.

### Quick Deployment (Patch Version)
```bash
python -m todoai_cli.deploy
```

### Version Bump Options
```bash
# Patch version (0.1.1 -> 0.1.2)
python -m todoai_cli.deploy --bump patch

# Minor version (0.1.1 -> 0.2.0)  
python -m todoai_cli.deploy --bump minor

# Major version (0.1.1 -> 1.0.0)
python -m todoai_cli.deploy --bump major
```

### Deployment Options
```bash
# Dry run (see what would happen)
python -m todoai_cli.deploy --dry-run

# Skip tests during deployment
python -m todoai_cli.deploy --skip-tests
```

### What the Deployment Script Does

1. **Version Bumping**: Updates version in both `todoai_cli/__init__.py` and `setup.py`
2. **Cleanup**: Removes old build artifacts (`build/`, `dist/`, `*.egg-info/`)
3. **Testing**: Runs pytest (optional, can be skipped with `--skip-tests`)
4. **Building**: Creates wheel and source distribution with `python -m build`
5. **Publishing**: Uploads to PyPI with `python -m twine upload dist/*`
6. **Git Operations**: 
   - Commits changes with message "Release vX.X.X"
   - Creates git tag
   - Pushes to origin main and tags

### Prerequisites for Deployment

- PyPI credentials configured (via `~/.pypirc` or environment variables)
- Git repository with `origin` remote configured
- Clean working directory (no uncommitted changes)

### Manual Deployment (if needed)

If you need to deploy manually:

```bash
# Clean and build
rm -rf build/ dist/ *.egg-info/
python -m build

# Upload to PyPI
python -m twine upload dist/*

# Git operations
git add -A
git commit -m "Release vX.X.X"
git tag vX.X.X
git push origin main
git push origin --tags
```

## Release Process

1. Ensure all changes are committed and pushed
2. Run tests: `python -m pytest`
3. Deploy: `python -m todoai_cli.deploy --bump [patch|minor|major]`
4. Verify package on PyPI: https://pypi.org/project/todoai-cli/

