# Shop billing with Whop (SERBITO-593)

**Why:** a shop pays 30 € per month for Javi. 17 paying shops reach the 500 €/month goal (SERBITO-591).
Owner decision 2026-10-09: a Whop subscription on the same Whop business as serbito, 30 days free,
after the trial the unverified-shop limits apply until the shop pays.

## How it works

| Part | What it does | Code |
|---|---|---|
| Flag | `JAVI_BILLING_ENABLED` (default off). Off: no billing UI, no billing limits. The webhook works in both states. | `config/settings.py` |
| Trial | 30 days from registration (`Shop.created_at`). A shop registered before `JAVI_BILLING_START_DATE` starts its trial on that day. Computed, no data change. Staff can set "trial ends (override)" in the admin. Flag on without the start date: no billing limits, one ERROR in the logs. | `billing/services.py::trial_ends_at` |
| Status | `trial`, `active`, `past_due`, `canceled` on `ShopSubscription`. Whop `trialing`/`active`/`canceling` → `active`; `past_due`/`unresolved` → `past_due`; `canceled`/`expired`/`completed` → `canceled`. | `billing/models.py` |
| Access | `active` → yes. `past_due` → yes for `JAVI_BILLING_PAST_DUE_GRACE_DAYS` (7) while Whop retries. `trial`/`canceled` → yes until the trial ends. | `services.has_access` |
| Limits | No access → the unverified-shop limits (`SEND_LIMIT_TRIAL_*`, Serbian mobile numbers only). Payment does not replace the staff check: an unverified shop that pays stays on trial limits until staff ticks "sending verified". | `notifications/quotas.py` |
| Checkout | Store profile → "Subscribe" (POST) → `POST /checkout_configurations` with an inline hidden renewal plan on `WHOP_PRODUCT_ID`: `renewal_price` 30, `initial_price` 0, `billing_period` 30, `currency` eur, `trial_period_days` = the days left of the app trial (none after the trial). So a shop that subscribes on day 10 pays first on day 30. Metadata: `shop_id` + `shop_token` (HMAC). Redirect only to `https` on `whop.com`. | `services.start_checkout` |
| Webhook | `POST /billing/whop/webhook/`, Standard Webhooks signature (same code as serbito), ±5 min. `membership.*` → read the membership from the API (events can come out of order) and store it. `payment.succeeded` → `BillingPayment`. `payment.failed`/`requires_action` → re-read the membership. `refund.*` → re-read the payment, store the refunded amount. Other business, other product or no shop match → ignored, 200. | `billing/views.py` |
| run.app | Cloudflare Bot Fight Mode challenges Whop on serbito.rs hosts (serbito SERBITO-526). The run.app guard serves only this one path, signed. | `common/run_app_guard.py` |
| Admin | "Shop subscriptions" (filter by status: the paying shops) and "Billing payments". | `billing/admin.py` |
| Report | `manage.py billing_report --month YYYY-MM`: paying shops, gross, refunds, est. net after ~17% fee, shops by status. Counts only. | `billing/management/commands/` |
| Sync | `manage.py billing_sync`: re-reads every known membership (a lost webhook). | same |

The landing already says "30 days free, then 30 € per month, no card needed to start; without
payment the trial limits stay". The code does exactly this. Change both together.

## Owner steps

Do not paste keys or secrets into chat, Jira, GitHub or a file.

### 1. Whop (the live business that serbito uses)

1. **Products → Create product** "Javi". Visibility: hidden. Copy the product id `prod_…`.
   No plan is needed: the app creates a hidden 30 €/30-day plan for each checkout. Whop supports
   trials (`trial_period_days`); the app uses this only to keep the first charge at the end of the
   free 30 days. Do not add a trial to a dashboard plan: a shop would get the 30 days twice.
2. **Developer → Account API Keys → Create** `javi-prod`. No Admin role. Grant:
   `checkout_configuration:create`, `plan:create`, `payment:basic:read`, `member:basic:read`
   (memberships read). Not `developer:manage_webhook`. If a call later fails with 403, the error
   in the logs names the missing permission. Copy the key once.
3. **Developer → Webhooks → Create webhook**:
   - URL: `https://<javi run.app host>/billing/whop/webhook/`. Get the host with
     `gcloud run services describe javi --region europe-west1 --format='value(status.url)'`.
     Not `javi.serbito.rs` (Bot Fight Mode).
   - API version `v1`. Child resource events off.
   - Events: `membership.activated`, `membership.updated`, `payment.succeeded`, `payment.failed`,
     `payment.requires_action`, `refund.created`, `refund.updated`.
   - Copy the `ws_…` secret once.

Whop sends the events of the whole business to each webhook. Javi ignores serbito payments.
Serbito's webhook gets javi payments too and logs a WARNING "carries no valid order token" for
each; serbito's `whop_preflight` reports the javi webhook as "a payment webhook to another host".
Both are expected; a serbito ticket can allow the javi host.

### 2. Secrets (GCP project `serbito`)

```bash
pbpaste | tr -d '\n' | gcloud secrets create javi-whop-api-key --data-file=- --project serbito
pbpaste | tr -d '\n' | gcloud secrets create javi-whop-webhook-secret --data-file=- --project serbito
pbcopy < /dev/null
for s in javi-whop-api-key javi-whop-webhook-secret; do
  gcloud secrets add-iam-policy-binding $s --project serbito \
    --member=serviceAccount:javi-run@serbito.iam.gserviceaccount.com \
    --role=roles/secretmanager.secretAccessor
done
```

Copy the key (step 1.2) before the first command, the webhook secret (step 1.3) before the second.

### 3. Switch on (one commit on a branch, released as usual)

- `.github/workflows/deploy.yaml`, `RUN_SECRETS`: append
  `,WHOP_API_KEY=javi-whop-api-key:1,WHOP_WEBHOOK_SECRET=javi-whop-webhook-secret:1`
  (pinned versions, as in serbito). The deploy fails if a secret is missing.
- `.github/deploy.env.yaml`:

  ```yaml
  WHOP_SANDBOX: "0"
  WHOP_COMPANY_ID: "<serbito's live biz_ id>"
  WHOP_PRODUCT_ID: "<prod_ from step 1.1>"
  JAVI_BILLING_START_DATE: "<go-live day, YYYY-MM-DD>"
  JAVI_BILLING_ENABLED: "True"
  ```

- CHANGELOG `[Unreleased]`: "Shops can subscribe in the store profile."

Without `WHOP_SANDBOX: "0"` the calls go to the Whop sandbox.

### 4. Check

1. Whop → the webhook → **Test**: a 200 in the delivery log (401 = wrong secret).
2. Your test shop → store profile: "Free trial · N days left" and "Subscribe — 30 € / month".
3. Subscribe with a real card. Back on the profile within a minute: "Subscription is active".
   A shop in its trial is not charged now (Whop `trialing`). To test a charge, use a shop whose
   trial has ended (Admin → its subscription → "trial ends (override)" in the past).
4. Refund the test payment in the Whop dashboard. Admin → Billing payments shows the refund.
5. Report: `gcloud run jobs execute javi-migrate --region europe-west1 --wait --args=manage.py,billing_report,--month,YYYY-MM`.
   The job runs the image of the last release with migrations; this release has one.

### Switch off

Set `JAVI_BILLING_ENABLED: "False"` in `.github/deploy.env.yaml` and release. Fast, until the
next deploy: `gcloud run services update javi --region europe-west1 --update-env-vars JAVI_BILLING_ENABLED=False`.
Whop keeps charging active subscriptions: cancel them in the Whop dashboard if needed.
