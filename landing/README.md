# Javi — лендинг Этапа 0 (demand validation)

Статичный одностраничник для проверки спроса перед разработкой приложения.
См. бриф: `../docs/planning-artifacts/briefs/brief-Serbito-2026-06-01/brief.md`.

- **Цель:** собрать 5–10 заявок от магазинов на бюджете рекламы €50–100.
- **Языки:** сербский (по умолчанию), английский, русский. Переключатель + автоопределение по браузеру.
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

- `sitemap.xml` is hand-kept on purpose: two pages, and the image has no `.git` (file dates
  would be build dates, not edit dates). `config/test_seo.py` fails unless it lists exactly
  the public `landing/*.html` pages (a page with `<meta name="robots" content="noindex…">`
  is not public) and each URL answers 200. New landing page → add a `<url>` here.
- `robots.txt` disallows every private prefix Django serves; the same test fails when a new
  top-level route in `config/urls.py` is neither disallowed nor listed as crawlable.
  `/t/` stays crawlable so bots see its noindex; everything Django renders sends
  `X-Robots-Tag: noindex, nofollow` (`common/middleware.py`).
