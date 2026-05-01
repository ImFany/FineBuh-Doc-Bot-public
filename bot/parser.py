"""
Гибридный парсер данных счёта:
  Этап 1 — Gemini 2.0 Flash (первичный, google-genai SDK)
  Этап 2 — Regex-fallback (если нет ключа или Gemini недоступен)
  Этап 3 — FSM уточнение (если данных не хватает — в main.py)
"""
import re
import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from aiogram.fsm.state import State, StatesGroup

log = logging.getLogger(__name__)

# Модели перебираются по порядку: первая доступная по квоте используется
_GEMINI_MODELS = [
    'gemini-2.0-flash-lite',   # free-tier: 30 rpm / 1500 rpd
    'gemini-2.0-flash',        # запасная (платная или более высокая квота)
    'gemini-2.5-flash',        # резерв
]


# ─────────────────────────── FSM States ───────────────────────────

class InvoiceForm(StatesGroup):
    items          = State()   # ввод товаров
    delivery       = State()   # стоимость доставки
    buyer_inn      = State()   # ИНН покупателя
    buyer_name     = State()   # название (если нет в БД)
    buyer_kpp      = State()
    buyer_address  = State()
    buyer_director = State()
    buyer_rs       = State()
    buyer_bank     = State()   # банк + БИК + К/С одной строкой
    confirm        = State()
    edit_buyer     = State()   # редактирование реквизитов покупателя
    edit_items     = State()   # редактирование позиций (номер + qty + price)


# ─────────────────────────── Data classes ─────────────────────────

@dataclass
class Item:
    name:  str
    qty:   Decimal
    unit:  str
    price: Decimal          # цена С НДС

    @property
    def total(self) -> Decimal:
        return self.qty * self.price


@dataclass
class ParsedInvoice:
    items:      list[Item] = field(default_factory=list)
    delivery:   Decimal    = Decimal('0')
    buyer_inn:  str        = ''
    confidence: float      = 0.0   # 0..1


# ─────────────────────────── Helpers ──────────────────────────────

def _to_decimal(s: str) -> Decimal:
    return Decimal(s.strip().replace(' ', '').replace(' ', '').replace(',', '.'))


_RE_ITEM = re.compile(
    r'(?P<name>.+?)'
    r'[\s\-–—]+(?P<qty>\d+(?:[.,]\d+)?)'
    r'\s*(?P<unit>шт\.?|кг\.?|л\.?|м\.?|уп\.?|компл?\.?|пар\.?|ед\.?|pc\.?)'
    r'\s*[-–—]?\s*(?P<price>\d[\d\s ]*(?:[.,]\d{1,2})?)'
    r'\s*(?:руб(?:лей)?\.?|р\.?|₽)?',
    re.IGNORECASE | re.UNICODE,
)

_RE_DELIVERY = re.compile(
    r'доставк[аиу]\s*[-:–—]?\s*'
    r'(?P<price>[\d\s ]+(?:[.,]\d{1,2})?)'
    r'\s*(?:руб(?:лей)?\.?|р\.?|₽)?',
    re.IGNORECASE | re.UNICODE,
)
_RE_DELIVERY_REV = re.compile(
    r'(?P<price>[\d\s ]+(?:[.,]\d{1,2})?)'
    r'\s*(?:руб(?:лей)?\.?|р\.?|₽)?\s*[-–—]?\s*доставк[аиу]',
    re.IGNORECASE | re.UNICODE,
)

_RE_INN = re.compile(r'(?:инн|inn)\s*[:=]?\s*(?P<inn>\d{10,12})', re.IGNORECASE)
_RE_SKIP_LINE = re.compile(
    r'(?:инн|кпп|бик|огрн|р\s*/\s*с|расчётный\s+счёт|расчетный\s+счёт'
    r'|кор\.?\s*счёт|корр\.?\s*счёт|тел\.?\s*\d|e-mail|http)',
    re.IGNORECASE,
)
_RE_STRIP_NUM = re.compile(r'^\d+[\.\)]\s*')   # убирает «1. » / «10) » из начала названия


# ─────────────────────────── Local parser ─────────────────────────

def parse_local(text: str) -> ParsedInvoice:
    result = ParsedInvoice()

    m = _RE_INN.search(text)
    if m:
        result.buyer_inn = m.group('inn')

    work_text = text
    for pat in (_RE_DELIVERY, _RE_DELIVERY_REV):
        m = pat.search(work_text)
        if m:
            try:
                result.delivery = _to_decimal(m.group('price'))
                work_text = work_text[:m.start()] + work_text[m.end():]
                break
            except (InvalidOperation, ValueError):
                pass

    for line in work_text.splitlines():
        line = line.strip()
        if not line or len(line) < 5:
            continue
        if _RE_SKIP_LINE.search(line):
            continue
        m = _RE_ITEM.search(line)
        if not m:
            continue
        try:
            name  = _RE_STRIP_NUM.sub('', m.group('name').strip(' -–—:,')).strip()
            qty   = _to_decimal(m.group('qty'))
            unit  = (m.group('unit') or 'шт').rstrip('.')
            price = _to_decimal(m.group('price'))
            if price > 0 and 0 < qty <= 9999 and len(name) >= 3:
                result.items.append(Item(name=name, qty=qty, unit=unit, price=price))
        except (InvalidOperation, ValueError):
            continue

    if result.items:
        result.confidence = 1.0
    return result


# ─────────────────────────── Gemini client ────────────────────────

def _get_gemini_client(api_key: str):
    """Возвращает google.genai.Client."""
    from google import genai
    return genai.Client(api_key=api_key)


async def _gemini_generate(client, prompt: str,
                           image_bytes: bytes | None = None,
                           json_mode: bool = True) -> str:
    """Вызывает Gemini, перебирая модели при 429 (quota exceeded)."""
    from google.genai import types

    config = types.GenerateContentConfig(
        response_mime_type='application/json' if json_mode else 'text/plain'
    )
    contents: list = []
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'))
    contents.append(prompt)

    last_err: Exception = RuntimeError("No models available")
    for model in _GEMINI_MODELS:
        try:
            response = await client.aio.models.generate_content(
                model=model, contents=contents, config=config,
            )
            return response.text
        except Exception as e:
            if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                log.warning("Gemini quota on %s, trying next model…", model)
                last_err = e
                continue
            raise   # любая другая ошибка — пробрасываем
    raise last_err


# ─────────────────────────── Gemini: items ────────────────────────

async def _parse_gemini(text: str, api_key: str) -> ParsedInvoice:
    try:
        client = _get_gemini_client(api_key)
        prompt = (
            "Извлеки ВСЕ позиции товаров из текста счёта и верни ТОЛЬКО JSON:\n"
            '{"items":[{"name":"...","qty":1,"unit":"шт","price":0.00}],'
            '"delivery":0.00,"buyer_inn":""}\n'
            "Правила:\n"
            "- Включи КАЖДУЮ позицию, даже если список пронумерован (1. 2. 3. ...)\n"
            "- В поле name НЕ включай порядковый номер (без '1.' '2.' в начале)\n"
            "- Цены — итоговые (включают НДС 5%)\n"
            "- qty и price — числа, не строки\n\n"
            "Текст:\n" + text
        )
        raw = await _gemini_generate(client, prompt)
        data = json.loads(raw)

        result = ParsedInvoice()
        result.buyer_inn = data.get("buyer_inn", "")
        try:
            result.delivery = Decimal(str(data.get("delivery", 0)))
        except InvalidOperation:
            pass
        for it in data.get("items", []):
            try:
                raw_name = str(it.get("name", ""))
                name = _RE_STRIP_NUM.sub('', raw_name).strip()
                result.items.append(Item(
                    name=name,
                    qty=Decimal(str(it.get("qty", 1))),
                    unit=str(it.get("unit", "шт")),
                    price=Decimal(str(it.get("price", 0))),
                ))
            except (InvalidOperation, ValueError):
                continue
        result.confidence = 0.9
        return result
    except Exception as e:
        log.warning("Gemini items parse error: %s", e)
        return ParsedInvoice()


# ─────────────────────────── Public API ───────────────────────────

async def parse_invoice_text(text: str, api_key: str = '') -> ParsedInvoice:
    """Gemini — первичный парсер (точный); regex — запасной если нет ключа."""
    if api_key:
        gemini = await _parse_gemini(text, api_key)
        if gemini.items:
            return gemini
    return parse_local(text)


# ─────────────────────────── Buyer card parser ────────────────────

def _looks_like_buyer_card(text: str) -> bool:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 3:
        return False
    keywords = ['кпп', 'бик', 'р/с', 'к/с', 'банк', 'адрес', 'огрн', 'оквэд',
                'директор', 'руководитель', 'корр', 'расчётн', 'расчетн']
    tl = text.lower()
    return sum(1 for kw in keywords if kw in tl) >= 2


def _parse_buyer_card_regex(text: str) -> dict:
    r: dict = {}

    m = re.search(r'(?:инн)\s*[:/]?\s*(\d{10,12})', text, re.IGNORECASE)
    if m:
        r['inn'] = m.group(1)

    m = re.search(r'(\d{10,12})\s*/\s*(\d{9})', text)
    if m:
        r.setdefault('inn', m.group(1))
        r['kpp'] = m.group(2)

    m = re.search(r'кпп\s*[:/]?\s*(\d{9})', text, re.IGNORECASE)
    if m:
        r['kpp'] = m.group(1)

    m = re.search(
        r'(?:[рp][/\\][сc]|расч[её]тный\s+сч[её]т|расчетный\s+счет)'
        r'\s*[:\-]?\s*([\d]+)',
        text, re.IGNORECASE
    )
    if m:
        r['rs'] = m.group(1)

    m = re.search(r'бик\s*[:/]?\s*(\d{9})', text, re.IGNORECASE)
    if m:
        r['bik'] = m.group(1)

    m = re.search(
        r'(?:к[/\\]с|корр?\.?\s*сч[её]т|корреспондентский\s+сч[её]т)'
        r'\s*[:\-]?\s*([\d]+)',
        text, re.IGNORECASE
    )
    if m:
        r['ks'] = m.group(1)

    m = re.search(r'\bв\s+((?:АО|ПАО|ООО|НКО|Банк)[^\n,]{2,50})', text, re.IGNORECASE)
    if m:
        r['bank_name'] = m.group(1).strip().strip('"')

    return r


async def parse_buyer_card_from_image(image_bytes: bytes, api_key: str) -> dict:
    """Извлекает реквизиты покупателя из фото/скриншота через Gemini Vision."""
    if not api_key:
        return {}
    try:
        client = _get_gemini_client(api_key)
        prompt = (
            'Извлеки реквизиты контрагента с изображения и верни ТОЛЬКО JSON:\n'
            '{"name":"","inn":"","kpp":"","address":"","director":"",'
            '"rs":"","bank_name":"","bik":"","ks":""}\n'
            'name — полное юридическое наименование. '
            'Если поле не найдено — пустая строка.'
        )
        raw = await _gemini_generate(client, prompt, image_bytes=image_bytes)
        return json.loads(raw)
    except Exception as e:
        log.warning("Gemini image parse error: %s", e)
        return {}


async def parse_buyer_card(text: str, api_key: str = '') -> dict:
    """Извлекает реквизиты покупателя из произвольного текста через Gemini."""
    if api_key:
        try:
            client = _get_gemini_client(api_key)
            prompt = (
                'Извлеки реквизиты контрагента и верни ТОЛЬКО JSON:\n'
                '{"name":"","inn":"","kpp":"","address":"","director":"",'
                '"rs":"","bank_name":"","bik":"","ks":""}\n'
                'name — полное юридическое наименование с организационно-правовой формой. '
                'Если поле не найдено — пустая строка.\n\n'
                f'Текст:\n{text[:3000]}'
            )
            raw = await _gemini_generate(client, prompt)
            data = json.loads(raw)
            # Дополняем regex если Gemini что-то пропустил
            regex = _parse_buyer_card_regex(text)
            for k, v in regex.items():
                if not data.get(k):
                    data[k] = v
            return data
        except Exception as e:
            log.warning("Gemini buyer card parse error: %s", e)
    return _parse_buyer_card_regex(text)
