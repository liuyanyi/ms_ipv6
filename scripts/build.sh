#!/usr/bin/env bash
# Build source and wheel distributions into `dist/`.
set -euo pipefail

echo "Cleaning previous builds..."
rm -rf build dist *.egg-info

echo "Building distributions (sdist + wheel)..."
python -m build

echo "Build complete. Artifacts are in the ./dist directory:"
ls -lh dist

echo "Done."
