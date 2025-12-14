#!/usr/bin/env bash
# Upload built distributions in `dist/` to PyPI using `twine`.
# Requires `TWINE_USERNAME` and `TWINE_PASSWORD` env vars, or a configured `~/.pypirc`.
set -euo pipefail

if [ ! -d "dist" ]; then
  echo "dist/ not found. Run scripts/build.sh first." >&2
  exit 2
fi

echo "Checking distributions in dist/..."
ls -lh dist

echo "Uploading to PyPI via twine..."
twine check dist/*

# If TWINE_REPOSITORY_URL is set, twine will use it; otherwise uploads to PyPI.
if [ -n "${TWINE_REPOSITORY_URL:-}" ]; then
  twine upload --repository-url "$TWINE_REPOSITORY_URL" dist/*
else
  twine upload dist/*
fi

echo "Upload complete."
