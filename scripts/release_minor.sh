#!/usr/bin/env bash
# Release helper for javi: CHANGELOG -> gate (pytest, ruff, manage.py check, landing parse) ->
# commit -> next minor tag -> push -> GitHub Release. The v*.*.* tag triggers
# .github/workflows/deploy.yaml, which re-runs the same gate and deploys to Cloud Run.
# Entries for shops go into CHANGELOG.md under "## [Unreleased]" before the release. This script
# turns them into "## [X.Y.0] - date" in the release commit and refuses to release without
# entries (SERBITO-389, format: changelog.py).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}" # changelog.py needs only the standard library; PYTHON is for the script test

msg="${1:-}"
if [[ -z "$msg" ]]; then
  echo "Usage: $0 \"commit message\" [new_file ...]"
  echo "  Changes to tracked files are staged automatically (git add -u)."
  echo "  New files are staged only when listed, so stray drafts never ship."
  exit 1
fi
shift # the rest of "$@" are explicitly listed new files (may be empty)

branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" != "main" ]]; then
  echo "Release only from main (current: $branch)" >&2
  exit 1
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

# --- CHANGELOG: [Unreleased] -> [X.Y.0] - today. No entries: refuse before the gate, commit and tag ---
echo "==> CHANGELOG.md: ${next_tag#v}"
if ! "$PY" changelog.py release "${next_tag#v}"; then
  echo "Release $next_tag not made: add what shops get to CHANGELOG.md (README -> Releasing)" >&2
  exit 1
fi
notes="$("$PY" changelog.py notes "${next_tag#v}")"

# --- gate: tests always run and must pass before we tag — never skipped ---
echo "==> pytest"
uv run pytest
echo "==> ruff check"
uv run ruff check .
echo "==> ruff format --check"
uv run ruff format --check .
echo "==> manage.py check"
uv run python manage.py check

# --- gate: landing must exist and parse before we tag ---
echo "==> landing HTML parses"
python3 -c "import html.parser; html.parser.HTMLParser().feed(open('landing/index.html',encoding='utf-8').read()); print('landing OK')"

git add -u
if [[ $# -gt 0 ]]; then
  git add -- "$@"
fi

untracked="$(git ls-files --others --exclude-standard)"
if [[ -n "$untracked" ]]; then
  echo "WARNING: untracked files NOT included in this release (pass them as arguments to add):" >&2
  echo "$untracked" | sed 's/^/  /' >&2
fi

if git diff --cached --quiet; then
  echo "Nothing to commit — tagging current HEAD."
else
  git commit -m "$msg"
fi

git tag "$next_tag"
git push
git push origin "$next_tag"

echo "Released $next_tag"

# --- GitHub Release: the English lines of the version from CHANGELOG.md. Not fatal: the tag and
# the deploy are already on their way ---
retry="gh release create $next_tag --verify-tag --title $next_tag --notes \"\$($PY changelog.py notes ${next_tag#v})\""
if ! command -v gh >/dev/null 2>&1; then
  echo "WARNING: gh not found, no GitHub Release for $next_tag. Run: $retry" >&2
elif ! gh release create "$next_tag" --verify-tag --title "$next_tag" --notes "$notes"; then
  echo "WARNING: GitHub Release for $next_tag failed. Retry: $retry" >&2
fi
exit 0
