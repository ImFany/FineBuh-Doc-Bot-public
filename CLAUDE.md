# CLAUDE.md — FineBuh Doc Bot

> Этот файл даёт Claude контекст проекта при старте новой сессии.
> Обновляй после каждого крупного изменения.

---

## Проект

**Telegram-бот** `@FineBuh_Doc_Bot` для автоматической генерации пакета документов:
- Счёт PDF
- УПД PDF
- Договор поставки DOCX/PDF
- XML для ЭДО (1С-формат)

Продавец: **ИП Шавкова Тамара Расуловна**, ИНН 672508646399, г. Элиста, Республика Калмыкия.  
НДС: **5%** (включён в цену).

---

## VPS (production)

| Параметр | Значение |
|----------|----------|
| IP | `2.26.24.142` |
| Пользователь | `root` |
| Пароль | в `.env` на сервере / у владельца |
| Путь к боту | `/opt/docflow-bot/` |
| Venv | `/opt/docflow-bot/venv/` |
| Сервис | `docflow-bot.service` (systemd) |
| `.env` на VPS | `/opt/docflow-bot/.env` |

### Частые команды на VPS
```bash
# Подключение (paramiko в deploy.py или ssh напрямую)
ssh root@2.26.24.142

# Статус сервиса
systemctl status docflow-bot --no-pager -l

# Логи (последние 50 строк)
journalctl -u docflow-bot -n 50 --no-pager

# Перезапуск после обновления
systemctl restart docflow-bot

# Очистить pycache перед рестартом (важно!)
rm -rf /opt/docflow-bot/bot/__pycache__

# Установить/обновить зависимости
/opt/docflow-bot/venv/bin/pip install -r /opt/docflow-bot/requirements.txt
```

### Деплой файлов на VPS
Используй `deploy.py` (paramiko SFTP) — SSH-ключа нет, только пароль:
```bash
python deploy.py
```
Или вручную через paramiko в Python.

---

## Структура проекта

```
YT text import/          ← корень (локальная папка проекта)
├── bot/
│   ├── main.py          ← aiogram 3 хэндлеры, FSM, генерация документов
│   ├── parser.py        ← парсинг текста: Gemini (primary) + regex (fallback)
│   ├── generator.py     ← WeasyPrint PDF, python-docx, lxml XML
│   ├── db.py            ← SQLite: buyers, invoices, packages, counter
│   ├── config.py        ← константы продавца, пути, env-переменные
│   ├── num2words_ru.py  ← число прописью на русском
│   └── templates/
│       ├── invoice.html ← шаблон Счёт
│       ├── upd.html     ← шаблон УПД
│       └── contract.html← шаблон Договора (Jinja2)
├── deploy.py            ← деплой файлов на VPS через paramiko SFTP
├── forwarder.py         ← вспомогательный скрипт (не основной)
├── requirements.txt
├── .env.example         ← пример .env (без секретов)
├── CHANGELOG.md         ← история версий
└── CLAUDE.md            ← этот файл
```

---

## Технологии

| Компонент | Версия / библиотека |
|-----------|---------------------|
| Python | 3.11+ |
| Telegram Bot | aiogram 3.13.1 |
| AI парсинг | google-genai (SDK v1) — НЕ google-generativeai |
| PDF | WeasyPrint 62.3 + pydyf==0.10.0 |
| DOCX | python-docx 1.1.2 + docxtpl |
| XML | lxml 5.3.0 |
| БД | SQLite (bot/data/bot.db) |
| Окружение | python-dotenv |

> ⚠️ **requirements.txt** содержит `google-generativeai` — это устаревшее имя!  
> На VPS установлен **`google-genai`** (новый SDK). При обновлении зависимостей  
> нужно заменить на `google-genai>=1.0.0`.

---

## .env (шаблон)

```env
BOT_TOKEN=<токен от @BotFather>
GEMINI_API_KEY=<ключ Google AI Studio>
```

---

## База данных (SQLite)

Файл: `bot/data/bot.db`

| Таблица | Назначение |
|---------|------------|
| `buyers` | Кэш реквизитов покупателей по ИНН |
| `invoices` | История выставленных счетов |
| `packages` | Сохранённые FSM-пакеты для повторной генерации |
| `counter` | Автоинкрементный счётчик номеров (Б-000001) |

---

## FSM-состояния (InvoiceForm в parser.py)

```
items → delivery → buyer_inn → buyer_name → buyer_kpp → buyer_address →
buyer_director → buyer_rs → buyer_bank → confirm
                                            ↕
                                    edit_buyer / edit_items
```

**Шорткаты:**
- Если ИНН есть в `buyers` → бот пропускает все поля реквизитов, сразу confirm
- На экране `confirm` — 4 кнопки: ✏️ Реквизиты | ✏️ Позиции | ✅ Генерировать | ❌ Отмена

---

## Gemini AI (parser.py)

**Модели (fallback chain при 429):**
1. `gemini-2.0-flash-lite` — бесплатный тир: 30 req/min, 1500/day ← ОСНОВНАЯ
2. `gemini-2.0-flash`
3. `gemini-2.5-flash`

**Функции:**
- `parse_invoice_text(text, api_key)` — парсинг позиций из сообщения пользователя
- `parse_buyer_card(text, api_key)` — извлечение реквизитов из текста
- `parse_buyer_card_from_image(image_bytes, api_key)` — реквизиты из фото

---

## Команды бота

| Команда | Действие |
|---------|----------|
| `/start` | Приветствие |
| `/invoice` | Начать выставление счёта |
| `/edit_package` | Список последних 10 пакетов / загрузить пакет |
| `/cancel` | Отменить текущую операцию |
| `/help` | Справка |

---

## Текущая версия: 2.0.0 (2026-05-01)

### Что работает
- ✅ Gemini AI парсит все позиции (включая "37 шт" в названии, "-1шт")
- ✅ Buyer cache: при повторном ИНН бот не спрашивает реквизиты
- ✅ Экран подтверждения с редактированием позиций и реквизитов
- ✅ Команды удаления: `удали 9`, `удали последнюю`
- ✅ Реестр пакетов: `/edit_package` загружает предыдущий заказ
- ✅ FSM не перехватывает `/invoice`, `/help` и другие команды

### Известные ограничения
- ⚠️ Gemini free-tier: 1500 запросов/день. При превышении → авто-fallback на следующую модель
- ⚠️ `requirements.txt` содержит устаревший `google-generativeai` вместо `google-genai`

---

## GitHub

Репозиторий: **https://github.com/ImFany/FineBuh-Doc-Bot**

> ⚠️ Аккаунт ImFany имеет ограничения GitHub по торговым санкциям США.  
> Приватные репозитории заблокированы. Если нужен push — либо сделать репо  
> **публичным**, либо подать апелляцию: https://airtable.com/shrGBcceazKIoz6pY

Локальный git настроен, 2 коммита:
1. `feat: v2.0.0 — Gemini AI, edit buttons, buyer cache, package registry`
2. `chore: remove .claude session dir from tracking (contains credentials)`

---

## Как деплоить изменения

```python
# deploy.py использует paramiko
# Редактируй список файлов в deploy.py при добавлении новых
python deploy.py
# После деплоя на VPS:
# ssh root@2.26.24.142
# rm -rf /opt/docflow-bot/bot/__pycache__
# systemctl restart docflow-bot
# journalctl -u docflow-bot -n 20 --no-pager
```

---

## Что делать в начале новой сессии

1. Прочитай этот файл + `CHANGELOG.md`
2. Проверь логи на VPS: `journalctl -u docflow-bot -n 30 --no-pager`
3. Спроси пользователя что нужно сделать
