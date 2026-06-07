# Plan: multi-channel notification fallback

**Requested:** a fallback chain `Telegram → Viber → WhatsApp → iMessage → SMS` for the
"delivery started" (and other) customer notifications.

**Intent (what we honor):** maximize the chance the customer actually receives the message,
by trying richer/cheaper/preferred channels first and falling back to a guaranteed one.

> ⚠️ **Reality check (must read first).** The requested *order* is not implementable as a
> linear proactive cascade — it is wrong at both ends. We keep the intent but correct the
> design. See "Feasibility" below. **Default proactive cascade becomes: Viber → WhatsApp →
> SMS, with Telegram and Apple Messages handled as opt-in / reply-only side channels.**

---

## 1. What already exists (review)

Grounded in a read of the current code (citations in the analysis; summary here).

**Provider layer** (`integrations/`)
- `MessagingProvider.send_text(to_e164, text) -> SendResult` is the only contract
  (`base.py`). `SendResult(ok, provider_message_id, channel)` where `channel` is the actual
  channel used (`base.py`). Comment scopes it to `viber|sms`.
- `InfobipProvider` already implements a **synchronous Viber→SMS fallback** internally
  (`infobip.py`): tries Viber, on failure falls back to SMS if `INFOBIP_SMS_FALLBACK`.
  Channel chosen via `INFOBIP_CHANNEL` (`viber|sms`).
- Construction via `get_messaging_provider()` factory + `settings.MESSAGING_PROVIDER`
  (`providers.py`), wrapped by `MeteringMessagingProvider` which counts `viber|sms` only
  (`metering.py`).
- Quota metering (just shipped, v0.39.0): `ProviderUsage` counts real sends per channel.

**Lifecycle** (`notifications/`, `deliveries/services.py`)
- `Notification` model: `Kind` (on_the_way | rating_request), `Channel` (**viber | sms only**),
  `Status` (queued→sent→delivered→read→failed), `provider_message_id`, `logical_message_id`.
- **One Notification row per (delivery, kind)** — `UniqueConstraint` on on_the_way. Channel
  is recorded as the single final channel, not per-attempt.
- Send is **synchronous → SENT/FAILED only**; DELIVERED/READ arrive **asynchronously** via
  Infobip report webhooks (`notifications/webhooks.py`, secret-guarded) → monotonic status
  updates → emits merchant webhooks. **So today we only know "send accepted", not "delivered",
  at send time.**
- Opt-out: phone-level `OptOut`; enforced for rating_request, intentionally NOT for
  on_the_way (critical). Phones normalized to E.164 (`common/phone.py`, region RS).

**Implication:** the Infobip Viber→SMS fallback is a *2-step, single-vendor, synchronous*
mechanism. A real multi-channel chain needs (a) more channels, (b) per-attempt records,
(c) capability/opt-in awareness, and (d) optional async escalation on delivery receipts.

---

## 2. Feasibility per channel (the hard constraints)

Verified against current Infobip/Telegram/Apple/Meta docs (2025–2026).

| Channel | Proactive cold send? | Via our Infobip? | Gate to launch | DLR for escalation |
|---|---|---|---|---|
| **Viber** | ✅ Yes | ✅ `/viber/2/messages` | Sender registration + "Transactional" qualification + opt-in (sender-level, fast) | ✅ delivered/seen |
| **WhatsApp** | ✅ Yes | ✅ WhatsApp channel | Meta business verification + **approved Utility template** + opt-in (slowest) | ✅ delivered/read |
| **SMS** | ✅ Yes | ✅ `/sms/2/text/advanced` | Sender ID; transactional is most permissive | ✅ delivered (no read) |
| **Telegram** | ❌ **No** | ⚠️ inbound-only (Conversations) | User must `/start` your bot first; bots cannot cold-message | ⚠️ weak |
| **iMessage / Apple Messages for Business** | ❌ **No** | ✅ channel exists | Customer must initiate via entry point; Apple forbids unsolicited outreach | n/a for proactive |

**Why the requested order fails:**
- **Telegram first** — a bot literally cannot message a user who hasn't started it. For a
  shop's one-off customer, that's ~always. It would no-op as a first touch.
- **iMessage at #4** — Apple Messages for Business is structurally customer-initiated; it
  cannot send a proactive notification at all. It's a *support/reply* surface, not a notify
  channel.
- Burying **Viber** (the Serbia workhorse, ~90%) behind Telegram and **SMS** (guaranteed
  reach) last is backwards for reliability.

**Corrected model:** branch on per-customer capability/opt-in flags, not a fixed line.
- Default proactive cascade: **Viber → WhatsApp → SMS** (all via existing Infobip vendor).
- **Telegram**: promote to first attempt *only* for customers who previously did `/start`
  (store `telegram_chat_id` as an explicit opt-in). Otherwise skip.
- **Apple Messages**: inbound/reply only (e.g. a "track my order" entry point), never in the
  proactive cascade. Out of scope for this plan beyond noting it.

---

## 3. Target architecture

Recommended seam: **`ChainedMessagingProvider`** (composition over modifying Infobip).

- Keep `MessagingProvider.send_text` contract. Add single-channel providers:
  `ViberProvider`, `WhatsAppProvider`, `SmsProvider` (thin, all Infobip-backed, factored out
  of today's `InfobipProvider`), plus a separate `TelegramProvider` (Bot API, different
  vendor path).
- `ChainedMessagingProvider(channels_for(recipient))` iterates an **ordered, capability-
  filtered** list, returns the first `ok` result with its real `channel`. Default order
  `[viber, whatsapp, sms]`; prepend `telegram` when the recipient is bot-opted-in.
- Capability resolution: a small `channel_chain_for(delivery)` that consults per-recipient
  flags (telegram opt-in; later: known-WhatsApp) + global enable flags (so WhatsApp can ship
  dark until template approved). Config via settings, overridable per environment.
- Metering/`Notification.Channel`/`ProviderUsage` extended to the new channel set; the
  metering whitelist (`metering.py`) replaced with a known-channels set (currently hardcoded
  to viber|sms — would silently drop new channels otherwise).

**Escalation policy (phased):**
- **Phase A — synchronous cascade only:** advance to the next channel only when the current
  `send_text` returns `ok=False` (mirrors today's Viber→SMS, just N-deep). Simple, no timers.
- **Phase B — DLR-driven escalation (optional, later):** send on channel 1, schedule a
  Cloud Tasks check after T minutes; if no DELIVERED receipt (or a FAILED/UNDELIVERABLE
  webhook arrives), escalate to the next channel. Reuses the existing async task + webhook
  infra. This is what makes "Viber didn't actually reach them → try WhatsApp/SMS" real, since
  send-accepted ≠ delivered.

**Data model changes:**
- Extend `Notification.Channel` choices (+ migration) — non-breaking (CharField).
- Track attempts: either multiple `Notification` rows per logical message, or a new
  `NotificationAttempt(notification, channel, status, provider_message_id, attempt_no,
  sent_at)`. Recommended: **NotificationAttempt** child rows; keep one logical `Notification`
  as the "winning"/current head. Enforce idempotency on `(delivery, kind, logical_message_id)`.
- `Customer`/recipient-level opt-in fields for Telegram (`telegram_chat_id`) and a future
  per-channel opt-out (today opt-out is phone-level, all-channels).

---

## 4. Proposed implementation order (roadmap)

Each phase is independently shippable (TDD), behind flags, no prod risk until enabled.

- **P0 — Refactor for N channels (no behavior change).** Extract `ViberProvider` +
  `SmsProvider` from `InfobipProvider`; introduce `ChainedMessagingProvider`; default chain
  `[viber, sms]` reproducing today's behavior exactly. Extend metering known-channels set.
  Full test parity. *Ships invisibly; de-risks everything after.*
- **P1 — Channel model + attempts.** Extend `Notification.Channel`; add `NotificationAttempt`
  (or multi-row) + idempotency key; record per-attempt channel/status; update receipt webhook
  to match attempts by `provider_message_id`. UI/API show the channel that won.
- **P2 — WhatsApp provider (synchronous cascade).** Add `WhatsAppProvider` (Infobip WhatsApp
  + Utility template). Default cascade `[viber, whatsapp, sms]`, WhatsApp behind a global
  enable flag (dark until Meta business verification + template approved). Ops checklist for
  template/opt-in.
- **P3 — Telegram opt-in side channel.** `TelegramProvider` (Bot API) + a `/start` opt-in
  capture storing `telegram_chat_id`; when present, prepend telegram to the cascade.
  Customer-initiated, so it's additive and safe.
- **P4 — DLR-driven async escalation (optional).** Cloud Tasks timeout + webhook-driven
  escalation so a non-delivered Viber actually escalates. Only worth it once ≥2 proactive
  channels are live.
- **Apple Messages for Business** — explicitly deferred / out of scope as a proactive
  channel; revisit only as an inbound support surface.

**Ops/external lead-time (not code, start early):** Viber sender "Transactional" registration;
Meta business verification + WhatsApp Utility template approval; Telegram bot creation.

---

## 5. Open decisions for the owner

1. **Confirm the corrected order** Viber → WhatsApp → SMS (default), Telegram as opt-in-only,
   Apple Messages dropped from the proactive chain. (Recommended.)
2. Synchronous cascade first (P0–P3), add async DLR escalation later (P4)? (Recommended.)
3. WhatsApp now or later — it carries the heaviest external approval lead time.

---

## 6. Fan-out / execution note

Planning was fanned out across 3 subagents (architecture map, lifecycle map, channel
feasibility research). Implementation will fan out per phase via worktree subagents where
tasks are independent (e.g. P2 WhatsApp provider vs P3 Telegram provider can run in parallel
once P0/P1 land), merged sequentially — mind shared files (`providers.py`, `metering.py`,
`Notification` migrations). See [[javi-fan-out-subagents]], [[javi-tdd-workflow]].

## Progress
- **Owner confirmed (2026-06-07):** corrected design (Viber → WhatsApp → SMS; Telegram opt-in
  only; Apple Messages dropped from proactive chain). Start P0 + P1.
- **Foundation** (`0f9faac`): `AttemptResult`/`SendResult.attempts`; `Notification.Channel`
  +telegram/+whatsapp, channel `max_length 16` (migr 0003); `MESSAGING_METRICS`.
- **P0 done** (`d66e6ea`, agent A): `ChainedMessagingProvider` + single-channel
  `ViberProvider`/`SmsProvider` (Infobip transport extracted); factory builds chain from
  `MESSAGING_CHAIN` (default = legacy Viber→SMS, byte-equivalent); `MESSAGING_PROVIDER=""`
  default so prod uses the chain; metering whitelist → `MESSAGING_METRICS`. No behavior change.
- **P1 done** (`aebf3d9` + integration `6c8bdc6`, agent B): `NotificationAttempt` (one row per
  channel tried, ordered) + idempotency `UniqueConstraint(delivery, kind, logical_message_id)`
  (migr **0004**, regenerated after a base-mismatch number collision); `_send_and_record`
  records attempts and sets the winning channel on `Notification`; receipts still match by the
  winning `provider_message_id`. API `notif.channel` now reflects the winner.
- **P0×P1 integration test** added: real chain Viber(fail)→SMS(ok) through `start_delivery`
  records attempts `[(1,viber,False),(2,sms,True)]`, winner sms. Full suite 201 green, ruff clean.
- Fanned out via 2 parallel worktree subagents (disjoint files); merged sequentially. Gotcha
  logged: worktree branches fork from `main`, not the current feature branch — agents must
  rebase onto the foundation, and migration numbers can collide (renumber on merge).
- **P0+P1 shipped: v0.40.0** (PR #3), prod healthy. First deploy stack under the renamed repo.
- **P2 done** (`5e20897`, agent): `WhatsAppProvider` (Infobip WhatsApp **template** send —
  business-initiated needs an approved Utility template; runtime text → single `{{1}}`
  placeholder). Slotted between Viber and SMS **only when `WHATSAPP_ENABLED`** (default False);
  soft-fails → chain falls through to SMS. Settings `WHATSAPP_ENABLED/SENDER/TEMPLATE_NAME/
  TEMPLATE_LANG`.
- **P3 done** (`220eb41`, agent): `TelegramProvider` (Bot API) + `TelegramContact(phone↔chat_id)`
  opt-in model (migration 0005) + secret-guarded bot webhook that captures opt-in from a shared
  contact. Provider **self-skips** (no HTTP, ok=False) for non-opted-in numbers, so it's safe
  **prepended first** and falls through to Viber for everyone else. `TELEGRAM_ENABLED` (default
  False) + `TELEGRAM_BOT_TOKEN`/`TELEGRAM_WEBHOOK_SECRET`.
- Fanned out P2+P3 as 2 parallel worktree subagents; hand-merged the two shared files
  (`providers.py` chain order, `settings.py`). Combined default chain when all flags on =
  `telegram → viber → whatsapp → sms`; all flags off (default) = unchanged `viber → sms`.
  Added combined-chain order tests. **Full suite 227 green, ruff clean, migrations consistent.**
- **External onboarding needed before turning channels on** (code is dark/flagged): WhatsApp =
  Meta business verification + approved Utility template + `WHATSAPP_SENDER`; Telegram = create
  bot, set webhook with secret, users opt in via shared-contact button.
- **Next:** P4 (async DLR-driven escalation) — optional, later.
