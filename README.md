# Javi — delivery notifications for small businesses

### → [javi.serbito.rs](https://javi.serbito.rs)

**Keep your customers informed about their delivery — without building your own system.**

Javi sends your customer an automatic **Viber or SMS** message the moment an order goes
out for delivery: an **estimated arrival time** and a **tracking link** they open in any
browser — no app to install. The result: fewer failed deliveries, happier customers, more
repeat orders.

Made for **small shops, restaurants, bakeries and online stores** that deliver with their
own courier but don't have a delivery-tracking system of their own.

## What it does

- 📦 Add the day's deliveries (customer name, phone, address) — or push them via API
- 🚚 Tap **"delivery started"** → the customer gets a Viber/SMS notification + a live status page
- ⏱ **Automatic ETA** from the route (with traffic), so the customer knows when to expect the courier
- ⭐ After delivery, the customer **rates it in one tap**
- 🔁 See notification status (delivered / read / failed), fix a number and resend, handle opt-outs

## Integrate in minutes (API)

Sign up, generate an API key in your store profile, and drive the whole flow over a simple REST API:

- **API docs (OpenAPI / Swagger): [javi.serbito.rs/api/docs/](https://javi.serbito.rs/api/docs/)**
- Create an order, mark it dispatched, get the tracking URL, and receive **signed webhooks**
  on every status change. Industry-standard statuses (`pending` → `ready_for_pickup` →
  `out_for_delivery` → `delivered`).
- **Sending limits** protect customers and the sender ID: per store per day and month, per
  phone number per day, and 3 resends per delivery. New stores start on a trial (lower
  limits, Serbian mobile numbers only) until verified. Over a limit nothing is sent and the
  API answers `429` (`403` for a number the store may not message yet).

## Tech

Django 6 on Google Cloud Run · Cloud SQL · Google Maps (geocoding + routes/ETA) ·
Infobip (Viber → SMS) · Cloud Tasks. Serbian (Latin) + English UI.

## Status

**Alpha** — in active development; expect changes and the occasional rough edge.

## Releasing

1. With every change shops notice, add an entry under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md):
   an English line `- ...` and a Serbian (Latin) line `  - SR: ...` under it.
2. On `main`: `bash scripts/release_minor.sh "message"`. It refuses to release when `[Unreleased]` is empty.
   Otherwise it dates the entries as `## [X.Y.0]`, runs the gate, tags, pushes and creates the GitHub Release.
3. The deploy fails for a tag without its `## [X.Y.Z]` section in CHANGELOG.md.
   Details: [SETUP_CICD.md](SETUP_CICD.md#7-day-to-day-release-flow).

## License

**[MIT](LICENSE)** — free and open source. Use it, modify it, build on it (incl. commercially);
just keep the copyright notice.

---

🇷🇸 **Javi — obaveštenja o isporuci za male prodavnice u Srbiji.** Kupac dobija Viber/SMS kada
porudžbina kreće i okvirno vreme kada stiže, sa linkom za praćenje (bez aplikacije). Manje
neuspešnih isporuka, zadovoljniji kupci, više ponovljenih porudžbina. Za prodavnice, restorane
i online shopove koji dostavljaju svojim kuririma, a nemaju svoj sistem za praćenje.

## Other projects

- **[GTD](https://gtd.serbito.rs/?utm_source=github&utm_medium=crosspromo&utm_campaign=readme)** — free GTD task manager with a Telegram bot · [source](https://github.com/alxndr-bnd/gtd)
- **[Planning Poker](https://poker.serbito.rs/?utm_source=github&utm_medium=crosspromo&utm_campaign=readme)** — free planning poker for scrum teams, no sign-up · [source](https://github.com/alxndr-bnd/planning-poker)
- **[Serbito](https://serbito.rs/?utm_source=github&utm_medium=crosspromo&utm_campaign=readme)** — classifieds in Serbia

Made by [No Handoff](https://www.linkedin.com/company/nohandoff/).
