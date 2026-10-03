#!/usr/bin/env bash
# Post-deploy check of the security headers on one URL (SERBITO-348).
# Usage: scripts/check_security_headers.sh https://<service>/
# Required: Strict-Transport-Security; X-Content-Type-Options: nosniff; X-Frame-Options or
# frame-ancestors in Content-Security-Policy; Referrer-Policy; Content-Security-Policy or
# Content-Security-Policy-Report-Only. Redirects are not followed: the checked response is the
# one the URL itself returns. Prints only the names of missing headers, never their values.
set -euo pipefail

url="${1:-}"
if [[ -z "$url" ]]; then
  echo "Usage: $0 <url>" >&2
  exit 2
fi

if ! raw="$(curl -sS -D - -o /dev/null --max-time 30 "$url")"; then
  echo "Header check: request to $url failed." >&2
  exit 1
fi

# Lower-case "name: value" lines without CR; the status line has no colon-separated name.
headers="$(printf '%s\n' "$raw" | tr -d '\r' | awk -F': *' 'NF > 1 { print tolower($1) ": " tolower(substr($0, index($0, ":") + 1)) }')"

has() { printf '%s\n' "$headers" | grep -q "^$1:"; }
value_has() { printf '%s\n' "$headers" | grep "^$1:" | grep -q -- "$2"; }

missing=()
has "strict-transport-security" || missing+=("Strict-Transport-Security")
value_has "x-content-type-options" "nosniff" || missing+=("X-Content-Type-Options: nosniff")
if ! has "x-frame-options" && ! value_has "content-security-policy" "frame-ancestors"; then
  missing+=("X-Frame-Options or CSP frame-ancestors")
fi
has "referrer-policy" || missing+=("Referrer-Policy")
if ! has "content-security-policy" && ! has "content-security-policy-report-only"; then
  missing+=("Content-Security-Policy or Content-Security-Policy-Report-Only")
fi

if ((${#missing[@]})); then
  echo "Header check failed for $url. Missing:"
  printf '  - %s\n' "${missing[@]}"
  exit 1
fi
echo "Header check passed for $url."
