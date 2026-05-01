import asyncio
import logging
import os
from telethon import TelegramClient, events

# --- Configuration ---
API_ID = int(os.environ.get("TG_API_ID", "17782919"))
API_HASH = os.environ.get("TG_API_HASH", "e635b0472e06bb24e425877589701659")
SESSION_NAME = "forwarder"

SOURCE_CHANNEL = "LPRalarm"
TARGET_CHANNEL = os.environ.get("TG_TARGET_CHANNEL", "NF_alarm")

KEYWORDS = [
    "Сак",           # Саки, Саках, Саками, Сакский...
    "Новофедоровк",  # Новофедоровка, Новофедоровки, от Новофедоровки...
]

# Слова, означающие отбой тревоги
ALLCLEAR_WORDS = ["отбой", "отмена", "отменяется"]

# Эти слова триггерят только при отбое
ALLCLEAR_ONLY_KEYWORDS = [
    "Республика Крым",
    "по всему Крыму",
]

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("forwarder.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def message_matches(text: str) -> list:
    if not text:
        return []
    tl = text.lower()
    matched = [kw for kw in KEYWORDS if kw.lower() in tl]
    if not matched and any(w in tl for w in ALLCLEAR_WORDS):
        matched += [kw for kw in ALLCLEAR_ONLY_KEYWORDS if kw.lower() in tl]
    return matched


def get_marker(text: str) -> str:
    text_lower = text.lower()
    if any(w in text_lower for w in ALLCLEAR_WORDS):
        return "🟢"
    return "🔴"


async def main():
    if not TARGET_CHANNEL:
        raise ValueError("Не задана переменная TG_TARGET_CHANNEL")

    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()
    log.info("Клиент запущен, ожидаю сообщения из @%s", SOURCE_CHANNEL)

    source_entity = await client.get_entity(SOURCE_CHANNEL)

    @client.on(events.NewMessage(chats=source_entity))
    async def handler(event):
        text = event.message.text or ""
        matched = message_matches(text)
        if not matched:
            return

        marker = get_marker(text)
        log.info(
            "%s Совпадение [%s] — msg_id=%s: %.120s",
            marker,
            ", ".join(matched),
            event.message.id,
            text.replace("\n", " "),
        )
        source_link = f"https://t.me/{SOURCE_CHANNEL}/{event.message.id}"
        try:
            await client.send_message(
                TARGET_CHANNEL,
                f"{marker} {text}\n\n[Источник]({source_link})",
                link_preview=False,
            )
            log.info("Отправлено msg_id=%s", event.message.id)
        except Exception as exc:
            log.error("Ошибка при отправке msg_id=%s: %s", event.message.id, exc)

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
