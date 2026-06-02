---
title: "Javi — DESIGN"
status: final
created: 2026-06-02
updated: 2026-06-03
sources:
  - ../../prds/prd-javi-2026-06-01/prd.md
  - ../../architecture.md
colors:
  brand: "#4f7cff"          # основной бренд (CTA, on_the_way)
  accent: "#7a5cff"         # акцент (градиенты, бренд-шапка)
  # — Операторский кабинет (светлая тема «Clean») —
  bg: "#f4f6fb"
  surface: "#ffffff"
  ink: "#161b29"
  muted: "#6b7385"
  line: "#e4e8f0"
  # — Семантика статусов —
  status_on_the_way: "#4f7cff"
  status_delivered: "#16a34a"
  status_read: "#0ea5e9"
  status_failed: "#dc2626"
  rating: "#f5a623"
  # — Публичная страница (бренд) —
  brand_gradient_from: "#4f7cff"
  brand_gradient_to: "#7a5cff"
  on_brand: "#ffffff"
typography:
  font_family: "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
  weight_regular: 400
  weight_bold: 700
  weight_extrabold: 800
  size_display: "30px"      # крупный ETA, статус на публичной
  size_h: "18px"
  size_body: "15px"
  size_small: "13px"
  size_chip: "12px"
rounded:
  card: "14px"
  button: "12px"
  pill: "999px"
  phone: "26px"
spacing:
  unit: "4px"
  card_pad: "13px 14px"
  screen_pad: "16px 14px"
  gap: "10px"
components:
  - delivery_card
  - status_chip
  - primary_button
  - new_delivery_button
  - rating_stars
  - status_stepper
  - brand_header
---

# Javi — DESIGN

## Brand & Style
Javi — служебный, спокойный, надёжный. Голос — короткий и сервисный (не маркетинговый): «сообщаем факт, не продаём». Две поверхности делят бренд (синий→фиолетовый), но живут в разных регистрах: **операторский кабинет** — светлая утилита для использования «на бегу» (скорость и читаемость важнее атмосферы); **публичная страница получателя** — брендовая и тёплая (момент доверия). Эстетика унаследована от лендинга (`landing/`).

## Colors
- **Бренд:** `{colors.brand}` #4f7cff (CTA, статус «в пути»), `{colors.accent}` #7a5cff (акценты, градиент бренд-шапки).
- **Кабинет (светлый):** фон `{colors.bg}`, карточки `{colors.surface}`, текст `{colors.ink}`, вторичный `{colors.muted}`, границы `{colors.line}`.
- **Статусы (семантика, не украшение):** в пути `{colors.status_on_the_way}` · доставлено `{colors.status_delivered}` · прочитано `{colors.status_read}` · недоставлено `{colors.status_failed}` · оценка `{colors.rating}`.
- **Публичная:** градиент `{colors.brand_gradient_from}`→`{colors.brand_gradient_to}` в шапке, текст на бренде `{colors.on_brand}`, тело — светлое (`{colors.surface}`/`{colors.bg}`).
- Контраст: текст на светлом — `{colors.ink}` (AA+); статус-цвета используются с текстом достаточного веса, не только цветом (см. Accessibility во EXPERIENCE).

## Typography
- Семейство `{typography.font_family}` (system-ui — быстро, нативно, без сетевых шрифтов).
- **Display** `{typography.size_display}` extrabold — крупный ETA и статус на публичной странице (самый важный сигнал).
- **H** `{typography.size_h}` — логотип/заголовки секций. **Body** `{typography.size_body}` — имена/основной. **Small** `{typography.size_small}` — адрес/вторичное. **Chip** `{typography.size_chip}` bold — статусы.

## Layout & Spacing
- Мобайл-first, одна колонка, крупные зоны касания. Шаг сетки `{spacing.unit}`.
- Отступ экрана `{spacing.screen_pad}`, карточки `{spacing.card_pad}`, межкарточный `{spacing.gap}`.
- Главная кнопка действия — на всю ширину, прижата к низу (большой палец). «＋ Nova dostava» — постоянная, внизу списка.

## Shapes
- Карточки `{rounded.card}`, кнопки `{rounded.button}`, чипы/пилюли `{rounded.pill}`. Скругления умеренные (утилита, не «игрушка»).

## Components
- **delivery_card** — surface, бордер `{colors.line}`, паддинг `{spacing.card_pad}`: имя (body bold) + адрес (small muted) + строка статуса (ETA + чип). Готовая к старту несёт primary-кнопку.
- **status_chip** — pill, `{typography.size_chip}` bold, цвет по семантике статуса (фон — светлый тинт, текст — насыщенный): `● U dostavi`, `✓ Pročitano`, `✓ Isporučeno`, `Nije dostavljeno`.
- **primary_button** — `{colors.brand}`, текст `{colors.on_brand}`, `{rounded.button}`, на всю ширину («Dostava je počela», «Pošalji ponovo»).
- **new_delivery_button** — `{colors.brand}` с тенью бренда, extrabold, иконка «＋», постоянная внизу.
- **rating_stars** — 5 звёзд `{colors.rating}` (активные) / `{colors.line}` (пустые), крупный тач-таргет.
- **status_stepper** — 3 сегмента (Primljeno · U dostavi · Isporučeno), активные `{colors.brand}`, будущие `{colors.line}`.
- **brand_header** — градиент-полоса (публичная), `{colors.on_brand}` текст: магазин + приветствие + крупный статус.

## Do's and Don'ts
- ✅ Кабинет — светлый и контрастный; статус читается за полсекунды; кнопки крупные (улица, перчатки).
- ✅ Статус кодируем цветом **и** текстом/иконкой (не только цветом).
- ✅ ETA — самый крупный элемент там, где он есть.
- ❌ Не тащить тёмную маркетинговую тему лендинга в кабинет.
- ❌ Не маркетинговый тон в служебных сообщениях.
- ❌ Не мелкие цели/плотные списки в операторском виде.
