#!/usr/bin/env bash
# Convenience script to build and upload a release to PyPI.
# Usage: ./scripts/release.sh [--repository-url <url>] [--skip-upload]
set -euo pipefail

REPO_URL=""
SKIP_UPLOAD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repository-url)
      REPO_URL="$2"
      shift 2
      ;;
    --skip-upload)
      SKIP_UPLOAD=1
      shift
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

echo "Running build script..."
./scripts/build.sh

if [ "$SKIP_UPLOAD" -eq 1 ]; then
  echo "Skipping upload as requested."
  exit 0
fi

if [ -n "$REPO_URL" ]; then
  export TWINE_REPOSITORY_URL="$REPO_URL"
fi

echo "Uploading to PyPI (or provided repository)..."
./scripts/upload_pypi.sh

echo "Release finished."
