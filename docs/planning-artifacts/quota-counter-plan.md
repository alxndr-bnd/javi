# Plan: free-tier quota counter (Viber / SMS / Maps)

Jira: follow-up SERBITO-345 (per-shop caps, Closed), SERBITO-356 (shops see their own caps, Closed) · leftover: real `FREE_QUOTA_VIBER/SMS` values — [SERBITO-484](https://serbito.atlassian.net/browse/SERBITO-484)

**Goal:** show every signed-in cabinet a read-only counter of how much of our **global,
account-wide** free quota is left for Viber, SMS and Google Maps. Provider credentials /
billing access are NOT exposed to shops — they only see a number. Per-shop quotas: later.

**Decision (from owner):**
- Collect usage **globally**, isolated from shops (no billing creds in the cabinet).
- Show the **global** remaining quota to **all** registered accounts.
- Source = **count our own real provider calls** (self-contained, no fragile external
  billing API, no extra secrets). Limits configurable via env. May drift slightly from the
  provider's real balance; acceptable for MVP, can add a real Infobip balance probe later.

## Design

Meter at the **provider boundary** (integrations layer), so counts == real quota-burning
calls (cache hits don't count; Viber→SMS fallback counts as the channel actually used).

- `integrations.models.ProviderUsage` — one row per `(metric, period)`, `count` int.
  `period` = `YYYY-MM` (UTC). `record(metric, n=1)` increments atomically via `F()`.
  Metrics: `viber`, `sms`, `maps_geocode`, `maps_route`.
- `integrations/metering.py` — thin wrappers `MeteringMapsProvider`,
  `MeteringRoutesProvider`, `MeteringMessagingProvider` that record then delegate.
- `integrations/providers.py` — wire wrappers (gated by `USAGE_METERING_ENABLED`).
  Maps order = `Caching(Metering(real))` so a cache hit never reaches the meter.
- `integrations/usage.py` — `quota_summary()` → buckets `Viber` (lifetime), `SMS`
  (lifetime), `Maps` = geocode+route (monthly). Each: `used / limit / remaining / pct`.
  60s cache to avoid per-request DB hits.
- settings: `USAGE_METERING_ENABLED`, `FREE_QUOTA_VIBER/SMS/MAPS` (env, documented defaults).
- `deliveries/context_processors.free_quota` → exposes summary to all authenticated cabinet
  pages; registered in TEMPLATES. Renders a compact block in the `⋯` menu of `_header.html`.

## Tasks

- [x] T1 — `ProviderUsage` model + migration `0003_providerusage` + `record()` (atomic `F()`, monthly bucket)
- [x] T2 — metering wrappers (`integrations/metering.py`) + wiring in `providers.py` (cache hit doesn't meter; channel from SendResult)
- [x] T3 — settings limits + `quota_summary()` (`integrations/usage.py`, 60s cache; monthly Maps vs lifetime Viber/SMS)
- [x] T4 — context processor `deliveries.context_processors.free_quota` + `⋯`-menu widget in `_header.html` + CSS
- [x] T5 — i18n (en default, sr: Besplatna kvota / Mape …) + ruff clean + full suite (180) green
- [x] T6 — removed committed dup `deliveries/views 2.py`

Not deployed by this work (no tag). Deploy = `scripts/release_minor.sh` → vX.Y.0 tag.

**Real prod limits set in `.github/deploy.env.yaml` (2026-06-07):**
- `FREE_QUOTA_MAPS=10000` — real Google free tier (calls/month per SKU).
- `FREE_QUOTA_VIBER=93` — remaining of the Infobip trial (93 of 100 free Viber, ~57 days
  left). Counter runs from 0, so it hits the real wall after 93 more of our sends.
- `FREE_QUOTA_SMS=0` — usage-only (no fixed free SMS count given yet); set a real number later.

Related: leaked Infobip key rotation → see `infobip-key-rotation.md` (scheduled soon).

## Progress
- **Maps reset aligned to Google's free tier (2026-06-07):** verified Google Maps free tier
  zeroes on the 1st of each calendar month at **midnight Pacific Time**. `usage_period` now
  buckets monthly metrics in `QUOTA_RESET_TZ` (default `America/Los_Angeles`) instead of UTC,
  so Maps usage zeroes exactly when Google resets. Added `tzdata` dep (slim image has no
  zoneinfo). Viber/SMS are lifetime → unaffected. (On branch `feature/multichannel-fallback`.)
- Implemented in one TDD pass (shipped v0.39.0). All tests pass, ruff clean.
- Counts our own real provider calls (no billing creds in cabinet). Widget shown read-only to
  every signed-in account in the `⋯` menu. Per-shop quotas: future work.
- Possible later refinements: real Infobip balance probe (operator-side) for money-accurate
  Viber/SMS remaining; split Maps into geocoding vs routes SKUs; an /ops-only detail page.
- **Docs audit 2026-10-05:** done. T1–T6 shipped in v0.39.0 (0b42e83, 89938d2); Pacific-time reset in v0.40.0 (73dbecb). Per-shop quotas shipped as caps (SERBITO-345, SERBITO-357). Since v0.68.0 (SERBITO-356) shops see their own caps; only staff see the platform quota. Leftover: `FREE_QUOTA_VIBER/SMS` are still trial-era values in `.github/deploy.env.yaml` — SERBITO-484, together with the own-sender work in SERBITO-477.
