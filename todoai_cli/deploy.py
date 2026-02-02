#!/usr/bin/env python3
"""
Deployment script for todoai-cli
Handles version bumping and PyPI publishing
"""

import re
import subprocess
import sys
from pathlib import Path

def get_current_version():
    """Get current version from __init__.py"""
    init_file = Path(__file__).parent / "__init__.py"
    content = init_file.read_text()
    match = re.search(r'__version__ = "([^"]+)"', content)
    if not match:
        raise ValueError("Version not found in __init__.py")
    return match.group(1)

def bump_version(current_version, bump_type="patch"):
    """Bump version number"""
    parts = current_version.split(".")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    
    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "patch":
        patch += 1
    else:
        raise ValueError("bump_type must be 'major', 'minor', or 'patch'")
    
    return f"{major}.{minor}.{patch}"

def update_version_files(new_version):
    """Update version in __init__.py and setup.py"""
    # Update __init__.py
    init_file = Path(__file__).parent / "__init__.py"
    content = init_file.read_text()
    content = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{new_version}"', content)
    init_file.write_text(content)
    
    # Update setup.py
    setup_file = Path(__file__).parent.parent / "setup.py"
    content = setup_file.read_text()
    content = re.sub(r'version="[^"]+"', f'version="{new_version}"', content)
    setup_file.write_text(content)
    
    print(f"Updated version to {new_version}")

def run_command(cmd, check=True):
    """Run shell command"""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Error: Command failed: {cmd}")
        print(f"Error: {result.stderr}")
        sys.exit(1)
    return result

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Deploy todoai-cli to PyPI")
    parser.add_argument("--bump", choices=["major", "minor", "patch"], default="patch",
                       help="Version bump type (default: patch)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without executing")
    parser.add_argument("--skip-tests", action="store_true", help="Skip running tests")
    parser.add_argument("--auto-confirm", action="store_true", help="Skip confirmation prompt (for CI)")
    
    args = parser.parse_args()
    
    # Get current version
    current_version = get_current_version()
    new_version = bump_version(current_version, args.bump)
    
    print(f"📦 Deploying todoai-cli")
    print(f"Current version: {current_version}")
    print(f"New version: {new_version}")
    
    if args.dry_run:
        print("DRY RUN - No changes will be made")
        return
    
    # Confirm deployment (skip in CI)
    if not args.auto_confirm:
        response = input(f"\nDeploy version {new_version}? (y/N): ").strip().lower()
        if response != 'y':
            print("Deployment cancelled")
            return
    
    try:
        # Update version files
        update_version_files(new_version)
        
        # Clean previous builds
        print("🧹 Cleaning previous builds...")
        run_command("rm -rf build/ dist/ *.egg-info/")
        
        # Run tests (optional)
        if not args.skip_tests:
            print("🧪 Running tests...")
            result = run_command("python -m pytest", check=False)
            if result.returncode != 0:
                print("Warning: Tests failed, but continuing deployment...")
        
        # Build package
        print("🔨 Building package...")
        run_command("python -m build")
        
        # Upload to PyPI (skip in CI - handled by workflow)
        if not args.auto_confirm:
            print("Uploading to PyPI...")
            run_command("python -m twine upload dist/*")
        
        # Git operations
        print("Creating git commit and tag...")
        run_command(f"git add -A")
        run_command(f'git commit -m "Release v{new_version}"')
        run_command(f"git tag v{new_version}")
        
        if not args.auto_confirm:
            run_command("git push origin main")
            run_command("git push origin --tags")
        
        print(f"Successfully prepared todoai-cli v{new_version}")
        if not args.auto_confirm:
            print(f"📦 Package available at: https://pypi.org/project/todoai-cli/{new_version}/")
        
    except Exception as e:
        print(f"Error: Deployment failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()