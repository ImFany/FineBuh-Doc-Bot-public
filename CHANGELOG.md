# Changelog — FineBuh Doc Bot

## [2.1.0] — 2026-05-02

### 📄 Обновлённые шаблоны документов

- **Договор поставки (DOCX)** — заменён программно-генерируемый шаблон на профессиональный юридический документ:
  - 11 разделов: предмет, порядок поставки, цена/оплата, приёмка, переход права собственности, форс-мажор, споры, конфиденциальность, срок действия, прочее
  - Форматирование Times New Roman, выравнивание по ширине
  - Удалён `_build_contract_template()` — шаблон теперь хранится как файл `contract.docx`
- **XML для ЭДО** — полностью переписан `generate_xml()` по структуре выгрузки 1С:Предприятие 8:
  - `СвИП` с полными атрибутами (`ИННФЛ`, `СвГосРегИП`, `ОГРНИП`, `ДатаОГРНИП`)
  - `АдрГАР` с детализацией (регион, район, населённый пункт, улица, здание)
  - `БанкРекв` вместо `РеквСчет`
  - `ДокПодтвОтгрНом`, `ИнфПолФХЖ1/2/3`, `ДопСведТов`, `СвПродПер`, `Подписант`
  - Уникальные UUID для каждой позиции

### ✨ UX-улучшения

- Мгновенная обратная связь: "Обрабатываю позиции..." при отправке данных
- Фото и документы теперь корректно обрабатываются в FSM (добавлен `F.text` фильтр)
- Сокращённые названия организаций: ООО, АО, ИП и т.д. в списке пакетов
- Единое сообщение с файлами: caption на медиа-группе с информацией о покупателе, количестве позиций и сумме

### 🔒 Безопасность (v2.0.1)

- Удалены захардкоженные credentials из `deploy.py` — переход на SSH-ключи и `.env.local`
- Input validation перед Gemini (MAX_INPUT_LENGTH, MAX_LINES, PRICE_LIMIT)
- Output validation: `validate_parsed_invoice()` проверяет ответ Gemini
- SQLite: context managers, WAL-режим, `busy_timeout`, `synchronous=NORMAL`
- Retention policy: `expires_at` в таблицах `buyers`, `invoices`, `packages`
- Маскирование банковских реквизитов в логах

### 🐛 Исправления

- Gemini JSON parsing: `_safe_parse_json()` с `raw_decode()` для обработки trailing data
- `cursor.rowcount` вместо `connection.rowcount` в `cleanup_expired()`
- Добавлены недостающие константы в `config.py` (RETENTION_DAYS_*, MAX_INPUT_LENGTH)

### 📝 Файлы изменены

- `bot/generator.py` — новый contract DOCX, переписан XML
- `bot/main.py` — UX: feedback, F.text filters, short org names, media group caption
- `bot/parser.py` — `_safe_parse_json()`, input/output validation
- `bot/db.py` — context managers, PRAGMA, retention policy
- `bot/config.py` — validation и retention константы
- `bot/templates/contract.docx` — новый шаблон договора
- `deploy.py` — SSH-ключи вместо паролей

---

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
