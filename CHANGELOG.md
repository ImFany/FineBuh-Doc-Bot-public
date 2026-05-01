# Changelog — FineBuh Doc Bot

## [2.0.0] — 2026-05-01

### 🔄 Миграция AI: OpenAI → Google Gemini

- Удалена зависимость `openai`
- Добавлены `google-genai`, `Pillow`
- Все AI-вызовы переведены на `google.genai` SDK (v1 API)
- Модели: `gemini-2.0-flash-lite` (primary) → `gemini-2.0-flash` → `gemini-2.5-flash` (fallback chain при 429)
- Gemini теперь **первичный** парсер позиций (regex — только запасной без API-ключа)
- Gemini Vision поддерживает фото реквизитов без PIL (через `Part.from_bytes`)

### ✏️ Редактирование перед генерацией

- Экран подтверждения: добавлены кнопки **✏️ Реквизиты** и **✏️ Позиции**
- `InvoiceForm.edit_buyer` — обновить реквизиты покупателя (текст / фото / файл / ИНН)
- `InvoiceForm.edit_items` — изменить qty/price позиции:
  - `1 2 11880` — позиция №1: кол-во 2, цена 11 880
  - `1 11880` — только цена
  - `удали 9` / `удали последнюю` — удалить позицию

### 💾 Реестр пакетов (SQLite)

- Новая таблица `packages` в `bot.db`
- После каждой генерации пакет сохраняется автоматически
- `/edit_package` — список последних 10 пакетов
- `/edit_package <id>` — загрузить пакет в FSM для повторной генерации

### 🐛 Исправления

- **FSM перехватывал /invoice и /help** — добавлен фильтр `~F.text.startswith('/')` на все 10 FSM-обработчиков
- **Пропуск позиций с "37 шт" в названии** — regex заменён Gemini как первичным парсером
- **Пропуск позиций "-1шт"** — расширен regex `[\s\-–—]+` перед qty
- **Buyer cache не работал** — `upsert_buyer()` падал на отсутствующем ключе `short_name`; исправлено явным `.get()`
- **Gemini 404 (v1beta)** — мигрировано с deprecated `google.generativeai` на `google.genai`
- **`config.GEMINI_API_KEY` AttributeError** — добавлен в `config.py`
- **Банковские реквизиты** — regex теперь понимает `Расчетный счет:` и `Корр. счет:`
- **Числовой префикс в именах позиций** — `_RE_STRIP_NUM` убирает `"2. Название"` → `"Название"`

### 📝 Обновлено

- `bot/parser.py` — полная перезапись (Gemini SDK, fallback chain, логирование)
- `bot/db.py` — таблица `packages`, функции `save/get/list_package`, fix `upsert_buyer`
- `bot/config.py` — добавлен `GEMINI_API_KEY`
- `bot/main.py` — edit FSM, /edit_package, _not_cmd filter, обновлён help text
- `requirements.txt` — google-genai, Pillow, pydyf; убран openai
- `.env` — `OPENAI_API_KEY` → `GEMINI_API_KEY`

---

## [1.0.0] — 2026-04-24 (initial deploy)

- Базовый бот: /invoice → Счёт PDF + УПД PDF + Договор PDF + XML
- OpenAI GPT-4o для парсинга позиций
- SQLite: buyers, invoices, counter
- Systemd сервис на VPS 2.26.24.142
