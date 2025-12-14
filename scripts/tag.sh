#!/usr/bin/env bash
# Create an annotated git tag and optionally push it.
# Usage: ./scripts/tag.sh v1.2.3 [--push]

set -euo pipefail

usage() {
  echo "Usage: $0 <tag> [--push]" >&2
  exit 1
}

[ $# -ge 1 ] || usage

TAG="$1"
shift || true
DO_PUSH=0

while [ $# -gt 0 ]; do
  case "$1" in
    --push)
      DO_PUSH=1
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      ;;
  esac
  shift
done

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "Tag $TAG already exists locally." >&2
  exit 1
fi

if git ls-remote --tags origin | grep -q "refs/tags/$TAG"; then
  echo "Tag $TAG already exists on origin." >&2
  exit 1
fi

echo "Creating annotated tag $TAG..."
git tag -a "$TAG" -m "Release $TAG"
echo "Tag created."

if [ "$DO_PUSH" -eq 1 ]; then
  echo "Pushing tag $TAG to origin..."
  git push origin "$TAG"
  echo "Tag pushed."
else
  echo "Skip push. Run: git push origin $TAG"
fi
