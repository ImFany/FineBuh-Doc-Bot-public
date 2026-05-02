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
| Пользователь | `docflow` (non-root для безопасности) |
| Путь к боту | `/opt/docflow-bot/` |
| Venv | `/opt/docflow-bot/venv/` |
| Сервис | `docflow-bot.service` (systemd) |
| `.env` на VPS | `/opt/docflow-bot/.env` |

### Частые команды на VPS
```bash
# Подключение
ssh docflow@2.26.24.142

# Статус сервиса
sudo systemctl status docflow-bot --no-pager -l

# Логи (последние 50 строк)
sudo journalctl -u docflow-bot -n 50 --no-pager

# Перезапуск после обновления
sudo systemctl restart docflow-bot

# Очистить pycache перед рестартом (важно!)
rm -rf /opt/docflow-bot/bot/__pycache__

# Установить/обновить зависимости
/opt/docflow-bot/venv/bin/pip install -r /opt/docflow-bot/requirements.txt
```

### ⚠️ SECURITY: Deployment credentials

🔴 **НИКОГДА** не коммитьте `.env.local` или SSH-ключи в git!  
Credentials хранятся:
1. **Локально:** `.env.local` (в `.gitignore`, не коммитится)
2. **На VPS:** `.env` в `/opt/docflow-bot/` (не в git)

Для безопасного деплоя используйте SSH-ключи:
```bash
# 1. Генерируем SSH-ключ (один раз)
ssh-keygen -f ~/.ssh/id_rsa_docflow -C "docflow deployment"

# 2. Копируем публичный ключ на VPS (один раз)
ssh-copy-id -i ~/.ssh/id_rsa_docflow.pub docflow@2.26.24.142

# 3. Создаём .env.local с credentials (локально, не коммитится)
cat > .env.local << 'ENVEOF'
BOT_TOKEN=<your_token>
GEMINI_API_KEY=<your_key>
DEPLOY_HOST=2.26.24.142
DEPLOY_USER=docflow
DEPLOY_KEY_PATH=~/.ssh/id_rsa_docflow
DEPLOY_REMOTE_DIR=/opt/docflow-bot
ENVEOF

# 4. Деплоим (credentials читаются из .env.local)
python deploy.py
```

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

## Текущая версия: 2.1.0 (2026-05-02)

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

Репозиторий: **https://github.com/ImFany/FineBuh-Doc-Bot-public**

> ⚠️ Аккаунт ImFany имеет ограничения GitHub по торговым санкциям США.  
> Приватные репозитории заблокированы. Если нужен push — либо сделать репо  
> **публичным**, либо подать апелляцию: https://airtable.com/shrGBcceazKIoz6pY

Локальный git настроен, 2 коммита:
1. `feat: v2.0.0 — Gemini AI, edit buttons, buyer cache, package registry`
2. `chore: remove .claude session dir from tracking (contains credentials)`

---

## Как деплоить изменения

### Подготовка (один раз):

```bash
# 1. Создайте SSH-ключ для деплоя
ssh-keygen -f ~/.ssh/id_rsa_docflow -C "FineBuh deployment"

# 2. Добавьте публичный ключ на VPS (требуется доступ к VPS)
ssh-copy-id -i ~/.ssh/id_rsa_docflow.pub docflow@2.26.24.142

# 3. Создайте локальный .env.local (НЕ коммитится в git!)
cat > .env.local << 'ENVEOF'
DEPLOY_HOST=2.26.24.142
DEPLOY_USER=docflow
DEPLOY_KEY_PATH=~/.ssh/id_rsa_docflow
DEPLOY_REMOTE_DIR=/opt/docflow-bot
ENVEOF
```

### Деплой (при каждом изменении):

```bash
# 1. Убедитесь, что .env.local существует и корректен
# 2. Запустите деплой
python deploy.py

# Скрипт автоматически:
#   ✓ Загружает файлы bot/ через SFTP
#   ✓ Обновляет зависимости в venv
#   ✓ Очищает __pycache__
#   ✓ Перезапускает systemd сервис
#   ✓ Показывает последние логи
```

### Проверка статуса:

```bash
ssh docflow@2.26.24.142
sudo systemctl status docflow-bot
sudo journalctl -u docflow-bot -n 20 --no-pager
```

---

## Что делать в начале новой сессии

1. Прочитай этот файл + `CHANGELOG.md`
2. Проверь логи на VPS: `journalctl -u docflow-bot -n 30 --no-pager`
3. Спроси пользователя что нужно сделать

