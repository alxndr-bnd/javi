#!/usr/bin/env bash
# Release helper for javi (Phase 0 — static landing). Adapted from
# planning-poker. Gates on the landing check, commits, bumps the minor
# version tag, and pushes — the v*.*.* tag triggers the Cloud Run deploy.
set -euo pipefail

msg="${1:-}"
if [[ -z "$msg" ]]; then
  echo "Usage: $0 \"commit message\""
  exit 1
fi

# --- gate: tests always run and must pass before we tag — never skipped ---
echo "==> pytest"
uv run pytest
echo "==> ruff check"
uv run ruff check .
echo "==> manage.py check"
uv run python manage.py check

# --- gate: landing must exist and parse before we tag ---
echo "==> landing HTML parses"
python3 -c "import html.parser; html.parser.HTMLParser().feed(open('landing/index.html',encoding='utf-8').read()); print('landing OK')"

git add .
if git diff --cached --quiet; then
  echo "Nothing to commit — tagging current HEAD."
else
  git commit -m "$msg"
fi

latest_tag="$(git tag --list 'v*.*.*' --sort=-v:refname | head -n 1)"
if [[ -z "$latest_tag" ]]; then
  next_tag="v0.1.0"
else
  version="${latest_tag#v}"
  IFS='.' read -r major minor patch <<<"$version"
  next_minor=$((minor + 1))
  next_tag="v${major}.${next_minor}.0"
fi

git tag "$next_tag"
git push
git push origin "$next_tag"

echo "Released $next_tag"
