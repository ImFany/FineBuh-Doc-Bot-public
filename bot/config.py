import os
from decimal import Decimal

# ---------- Продавец (ИП Шавкова) ----------
SELLER_NAME         = "ИП Шавкова Тамара Расуловна"
SELLER_SHORT_NAME   = "Шавкова Тамара Расуловна"
SELLER_INN          = "672508646399"
SELLER_OGRNIP       = "321508100337115"
SELLER_OGRNIP_DATE  = "14.07.2021"
SELLER_OGRNIP_DATE_FULL = "14 июля 2021 г."
SELLER_ADDRESS      = ("358004, Республика Калмыкия, г.о. город Элиста, "
                       "г Элиста, проезд Автомобилистов 3-й, д. 1")
SELLER_ADDR_REGION_CODE = "08"
SELLER_ADDR_REGION_NAME = "Республика Калмыкия"
SELLER_BANK_NAME    = 'ООО "Банк Точка" г. Москва'
SELLER_BIK          = "044525104"
SELLER_RS           = "40802810701500192674"
SELLER_KS           = "30101810745374525104"
SELLER_SIGNATURE    = "Шавкова Т. Р."
SELLER_CITY         = "г. Элиста"

# ---------- Налоги ----------
VAT_RATE  = Decimal("0.05")
VAT_LABEL = "5%"

# ---------- Настройки бота ----------
BOT_TOKEN       = os.getenv("BOT_TOKEN", "")
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")   # устарел, оставлен для совместимости

# ---------- Пути ----------
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DB_PATH       = os.path.join(BASE_DIR, "data", "bot.db")
OUTPUT_DIR    = os.path.join(BASE_DIR, "output")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# ---------- Прочее ----------
PAYMENT_DAYS = 3   # срок оплаты счёта (рабочих дней)
