# Test suite review (SERBITO-364, 2026-09-29)

Jira: SERBITO-364 (Closed) · optional follow-up (shared conftest fixtures): [SERBITO-484](https://serbito.atlassian.net/browse/SERBITO-484)

The pytest gate was reviewed for slow setup, tests that repeat each other, copy-paste that fits `parametrize`, and checks of framework behaviour.

## Before / after

| | Before | After |
|---|---|---|
| Tests | 514 | 474 |
| Wall time (`uv run pytest`) | 67 s | 3–4 s |
| App coverage (lines, excluding test modules) | 2556 / 2711 (94.28%) | 2556 / 2711 (94.28%) |

Coverage is identical line by line.

## What changed, by category

**Speed: password hashing.**
- The default PBKDF2 hasher cost 0.1–0.3 s per `create_user` and `client.login`, and the suite creates hundreds of shops. That was about 95% of the gate.
- `conftest.py` now sets the MD5 hasher for the test session.
- No test depends on the algorithm, and production settings are unchanged.

**Copy-paste collapsed, with the same or wider coverage:**
- Login required: seven tests covered five hand-picked `/app/` URLs, one of them twice. `test_cabinet_requires_login` now walks every `deliveries.urls` route with GET and POST, so a new view without `LoginRequiredMixin` fails on its own.
- Tenant isolation, UI: four "other shop gets 404" tests became one that walks every `/app/dostava/<pk>/` route.
  - `ready` and `restore` had no such check before.
  - The test also checks that the victim's delivery is unchanged.
- Tenant isolation, API: get, start, ready and delete of another shop's delivery are now one test.
- Missing, bogus and revoked API keys: four 401 tests became one.
- Tracking pages: nine tests in `config/test_analytics`, `test_consent` and `test_seo` became one parametrized test, `tracking/tests.py::test_tracking_pages_stay_private`.
  - The old tests covered no GA, no consent banner and noindex, each with its own token fixture.
  - The new test checks all three for each link state (live, unsubscribe, expired, unknown, no slash).
- Infobip delivery reports: eight tests in two files posted the same four reports; one set checked the status, the other the merchant webhook. One parametrized test now checks both, and that exactly the expected event, or none, is emitted.

**Exact duplicates and framework behaviour:**
- `deliveries/tests`:
  - `test_tenant_isolation` had no deliveries, so it proved nothing. Its shop-scoping assert moved to `test_delivery_isolation_between_shops`.
  - `test_create_delivery_foreign_phone_flags_risk` is covered by `test_quotas`.
- `deliveries/test_api`:
  - `test_list_excludes_soft_deleted` was contained in the soft-delete test, now renamed for what it checks.
  - `test_create_put_method_not_allowed` tested DRF's own 405.
  - `test_docs_endpoint_public_200` is requested by `test_seo` and `test_security_headers`.
  - `test_generate_key_view_shows_plaintext_once` is covered by the JAVI-13 test, which checks more.
- `deliveries/test_webhook_profile::test_profile_requires_login` was an exact copy of another test.
- `config/test_analytics`: the three "has GA" tests are covered by `test_consent::test_consent_default_precedes_gtag_config`.
- `integrations/tests::test_default_chain_unchanged_when_flags_off` duplicated the same test in `test_whatsapp`.
- `notifications/test_outbound`:
  - the empty-secret HMAC case uses the same formula as the main signature test;
  - `test_recipient_phone_can_be_verified_by_merchant` (misnamed) recomputed a signature already checked.
- `tracking/tests::test_rate_limit_429` is one case of `test_rate_limit_covers_every_tracking_endpoint` (JAVI-8).

## Kept on purpose

- Security (SERBITO-345, -357, -362):
  - lockout, signup limits, Sentry scrubbing and secrets kept out of logs;
  - webhook, callback and Telegram secret checks for each endpoint (they prove each endpoint uses the check);
  - rate limits and XFF handling;
  - https-only merchant webhooks;
  - quotas (`test_quotas.py`, the whole file).
- Payment and tracking webhook flows: only duplicates were merged, and no assertion was dropped.
- Source guards tied to incidents: `test_dockerfile`, `test_deploy_workflow`, `test_docs_links`, `test_landing_contrast`.
- Bug regressions: a user without a shop gets no 500; the tracking stepper fix.

## Unsure (listed, not changed)

- `integrations/tests.py` :241–:291: the legacy `InfobipProvider` tests mirror the default-chain tests. Keep them while `MESSAGING_PROVIDER` can select that provider, and drop them together with it.
- `integrations/test_whatsapp.py` :141, :196, :66 overlap the metering and single-channel tests.
- `deliveries/tests.py`:
  - `test_fallback_chain_records_attempts_and_picks_winner` uses a stubbed result and duplicates the real-chain test;
  - `test_receipt_updates_parent_via_winning_message_id`;
  - `test_profile_post_success_redirects_and_saves`;
  - `test_resend_view_success`;
  - `test_mark_delivered`;
  - `test_logical_message_uniqueness_constraint`, which tests a DB constraint.
- `deliveries/test_api.py`:
  - the single ready/delivered lifecycle tests could fold into `test_status_mapping_across_lifecycle`;
  - `test_schema_endpoint_public_200`;
  - `test_start_already_started_returns_state`.
- `deliveries/test_webhook_profile.py`:
  - `test_save_webhook_settings` (it accepts 200 or 302);
  - `test_profile_shows_webhook_fields`;
  - the two URL-validation tests could be one parametrized test.
- `common/test_logging::test_settings_send_json_to_stdout` mirrors the `LOGGING` dict.
- `config/test_sentry::test_test_process_has_no_active_sentry_client` and `config/test_security_headers` :125/:130 check the test environment or source text.
- `accounts/tests.py`: `test_email_login` and `test_register_get_renders_form`.
- Setup duplication:
  - a shop/user factory is written in 16 files;
  - the tracking-token setup is repeated;
  - class-level fakes (`FakeMessagingProvider.sent`, `RecordingWebhookScheduler.webhooks`) are reset by hand about 25 times.

  One conftest fixture each would shorten many tests. That is a larger mechanical refactor, left for a follow-up.
