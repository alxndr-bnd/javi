# Javi — лендинг Этапа 0 (demand validation)

Статичный одностраничник для проверки спроса перед разработкой приложения.
См. бриф: `../docs/planning-artifacts/briefs/brief-Serbito-2026-06-01/brief.md`.

- **Цель:** собрать 5–10 заявок от магазинов на бюджете рекламы €50–100.
- **Языки:** сербский (`/`), английский (`/en/`), русский (`/ru/`) — отдельная статичная страница на язык (SERBITO-459). Переключатель — обычные ссылки, без автоопределения по браузеру.
- **Атрибуция:** UTM-параметры (`utm_source/medium/campaign`) из URL автоматически попадают в заявку — видно, какой канал (Google/Telegram) сработал.

## 1. Приём заявок — ✅ подключено (Formspree)

Форма отправляет заявки на **Formspree** endpoint `https://formspree.io/f/mgoqjnny`
(бесплатный тариф ~50 заявок/мес, хватает для Этапа 0). Заявки приходят на email,
JS отправляет через AJAX и сам показывает экран «Спасибо».

> Первая отправка с нового домена потребует разовое подтверждение email во Formspree.

Альтернативы (если понадобится сменить): Netlify Forms, Google Forms (iframe),
Telegram-бот через webhook, или собственный endpoint на существующем Django.

## 2. Куда задеплоить (`javi.serbito.rs`)

Это один статичный файл — подойдёт любой статик-хостинг:
- **Netlify / Cloudflare Pages / GitHub Pages** — перетащить папку, привязать поддомен `javi.serbito.rs` (CNAME).
- Либо отдать как статику с существующего сервера.

Локальный просмотр:
```
cd landing && python3 -m http.server 8080
# открыть http://localhost:8080
```

## 3. Запуск рекламы

Ссылки для кампаний с UTM (примеры):
- Google Ads: `https://javi.serbito.rs/?utm_source=google&utm_medium=cpc&utm_campaign=stage0`
- Telegram Ads: `https://javi.serbito.rs/?utm_source=telegram&utm_medium=ads&utm_campaign=stage0`

## 4. Гейт (из брифа)

- **≥5 заявок** от реальных магазинов → строим MVP (Этап 1).
- **<5 заявок** на €50–100 → пересмотр оффера/канала/гипотезы до написания кода.

## Открытое (не блокирует запуск)
- Базовая веб-аналитика (Plausible / GA4) — добавить счётчик для конверсии «визит → заявка».
- Политика конфиденциальности (нужна для рекламных площадок и сбора контактов) — короткая страница.

## SEO: robots.txt and sitemap.xml (SERBITO-303)

- `sitemap.xml` is hand-kept on purpose: four pages, and the image has no `.git` (file dates
  would be build dates, not edit dates). `config/test_seo.py` fails unless it lists exactly
  the public `landing/**/*.html` pages (a page with `<meta name="robots" content="noindex…">`
  is not public) and each URL answers 200. New landing page → add a `<url>` here.
- `robots.txt` disallows every private prefix Django serves; the same test fails when a new
  top-level route in `config/urls.py` is neither disallowed nor listed as crawlable.
  `/t/` stays crawlable so bots see its noindex; everything Django renders sends
  `X-Robots-Tag: noindex, nofollow` (`common/middleware.py`).

## Languages and hreflang (SERBITO-459)

- One static page per language: `index.html` (sr, Latin script) at `/`, `en/index.html` at `/en/`,
  `ru/index.html` at `/ru/`. WhiteNoise serves a directory's `index.html` at the directory URL.
- Each page has its own `<html lang>`, `<title>`, description, H1, self canonical, `og:url`,
  `og:locale` (+ `og:locale:alternate`) and the same hreflang set: sr, en, ru, x-default = `/`.
- No script changes the text. Googlebot renders with `en-US`; the old `navigator.language`
  switch made Google index the English text for the Serbian URL. The header language switch is
  plain links. Nothing redirects by browser language or by a saved choice.
- Each page saves its language in `localStorage` `javi_lang`. Only the privacy page's consent
  banner reads it. App links (sign in, register) set the app language from the page language.
- CSS and the inline scripts must be the same on all three pages; only the words differ
  (`config/test_seo.py`). Change text → change it in all three files.
- `privacy.html` stays one page with all three languages (SERBITO-352 sections `#sr`, `#en`,
  `#ru`; the app and the consent banner link to them). It has no hreflang: one URL, no variants.
- `sitemap.xml` lists `/`, `/en/`, `/ru/` (with `xhtml:link` alternates) and `/privacy.html`.
  Edit a page → set its `<lastmod>` to the edit date.
- After a release with new or changed pages: in Search Console resubmit `sitemap.xml`
  and request indexing of the changed URLs.

## SEO polish (SERBITO-462)

- **Brand descriptor.** "Javi" alone is ambiguous in search. `<title>`, `og:site_name` and the
  schema `alternateName` carry the descriptor in the page language: sr «Javi — Viber/SMS
  obaveštenja o isporuci», en "Javi — Viber/SMS delivery notifications", ru «Javi — уведомления
  о доставке в Viber/SMS». Titles stay ≤ 60 characters. `og:title` keeps the benefit phrase.
- **JSON-LD.** Each language page has one `@graph`: `Organization` (No Handoff),
  `WebSite`, `WebPage` (this page's URL, title, description, language) and `SoftwareApplication`.
  The `@id`s are stable: `https://javi.serbito.rs/#organization`, `#website`, `#software`, and
  `<page URL>#webpage`. `SoftwareApplication` carries the `Offer` (see "Price" below).
  `config/test_seo.py` checks the graph against the page.
- **Redirects.** `/index.html`, `/en/index.html`, `/ru/index.html`, `/en`, `/ru` answer 301
  (`common/landing_whitenoise.py`; plain WhiteNoise answers 302).
- **consent.js cache.** Every page loads `/consent.js?v=<first 12 hex of its SHA-256>`, and
  `/consent.js` is served `public, immutable` for 10 years. Edit `consent.js` → update `?v=` in
  the three landings, `privacy.html` and `templates/base.html`. `config/test_consent.py` fails
  with the right value until you do:
  `shasum -a 256 landing/consent.js | cut -c1-12`.

## Seller content and the request funnel (SERBITO-595)

- **Search terms.** Title = descriptor + the search phrase, ≤ 60 characters. H1 and description
  name Viber, SMS and delivery notifications to customers; the description (≤ 155) has the price.
- **Sections** on every language page: hero with one CTA (registration) and the trial line, who
  it is for, how it works (3 steps), features, price (`#cena`), FAQ (`#pitanja`), who runs Javi
  (`#o-nama`), the lead form (`#prijava`). Section ids are the same in every language.
- **Price.** 30 €/month per shop, the first 30 days free (SERBITO-593). Viber/SMS messages are
  included, with no limit shown. After 30 days payment is required; without it the trial limits
  stay. The page names no checkout page, payment method or date. Change the price → change the page text,
  the `Offer` in JSON-LD (`config/test_seo.py` checks both) and the registration page line.
- **FAQPage.** The JSON-LD questions and answers are the visible FAQ, word for word (tested).
- **Who runs Javi.** No Handoff, the owner's company (owner answer, 2026-10-09), the MIT licence,
  public GitHub, alpha. No street address or personal data on the page.
- **Icons.** `favicon.ico` (16/32/48) and `apple-touch-icon.png` (180×180, opaque) are files in
  `landing/`, drawn from the same "j" logo as the inline SVG icon. Every landing page, `privacy.html`
  and `templates/base.html` link all three (`config/test_landing_media.py`).
- **Organization (JSON-LD).** `url` is `https://javi.serbito.rs/`, LinkedIn is in `sameAs`,
  `logo` is the apple-touch icon.
- **Product proof.** `img/viber-poruka.*` (the customer's Viber message) and `img/pracenje-dostave.*`
  (the tracking page) sit under "how it works": AVIF with a WebP fallback, `width`/`height`,
  `loading="lazy"`, alt text in the page language. Both are in Serbian and made from the app with
  test data only (shop "Cvećara Demo", no real person or phone). The message text is the real
  `_on_the_way_text` output; the tracking page is a screenshot of `/t/<token>/` at 360×600 CSS px
  (×2), cropped to 720×1000. To remake them: seed a throwaway SQLite DB with one such delivery
  (ETA 14:30, a fixed "now" before it), screenshot with Playwright, export AVIF/WebP with Pillow.
  The message changes → remake the image.
- **Funnel.** The server counts browser views of `/`, `/en/`, `/ru/` and registration form opens per
  day (`common/funnel.py`, table `common_funnelcount`, no visitor data). Sign-ups and activated
  shops (first started delivery) come from `Shop` / `Delivery`. GA4 gets `landing_view`,
  `cta_click` (`data-cta` on each CTA), `lead_submit`, `signup_start`, `signup_complete`.
  Weekly report: `uv run python manage.py funnel_report --weeks 8` (read-only, counts only).

## Why Javi, facts block and llms.txt (SERBITO-597)

- **Facts block** `#sta-je-javi` sits right after the hero: one summary sentence plus a `<dl>` with
  what / for whom / price / where / who makes it. AI answers quote short factual blocks like this.
- **Why Javi** `#zasto` (before the price): 8 strengths and a comparison table Javi vs "foreign
  dispatch tools" vs "delivery platforms". Categories only, no competitor product names (unfair
  advertising risk); the note under the table says so and gives the date. On a phone each row is a
  card, and each cell shows its column name from `data-label`.
- **Claims.** Only what Javi does today (owner positioning, 2026-10-09). Never claim live courier
  GPS, multi-stop routes or shop-platform plugins; the table and FAQ say "no" to GPS and routes.
  Research: Basic Memory `reference/javi — аналоги и конкуренты в Сербии (2026-10)`.
- **FAQ** has the questions people ask AI assistants (when does the delivery arrive, Viber
  notifications for an online shop, an alternative to foreign tools). FAQPage JSON-LD = visible FAQ.
- **`llms.txt`** (served as `text/plain; charset="utf-8"`) states the same facts in English and
  Serbian. No page links to it; robots.txt allows it. Change the price, trial, channels or
  operator → change `llms.txt` too (`config/test_landing_geo.py` checks the key sentences).
