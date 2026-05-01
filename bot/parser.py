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
    'gemini-2.5-flash-lite',         # free-tier (стабильная, июль 2025)
    'gemini-2.5-flash',              # free-tier (стабильная)
    'gemini-3.1-flash-lite-preview', # free-tier (preview)
    'gemini-2.5-pro',                # free-tier (при превышении выше)
    # gemini-3.1-pro-preview — платная, не используем
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

def _safe_parse_json(raw: str) -> dict:
    """Robustly parse JSON from Gemini response, handling code fences and trailing data."""
    text = raw.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```\s*$', '', text)
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(text)
        return obj


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
        data = _safe_parse_json(raw)

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

# ─────────────────────────── Input Validation ─────────────────────────────────

def validate_input(text: str, max_length: int = 5000, max_lines: int = 100) -> tuple[bool, str]:
    """
    Validate user input before sending to Gemini API.
    
    Returns: (is_valid, error_message)
    """
    if not text or not text.strip():
        return False, "Текст не может быть пустым"
    
    # Check length
    if len(text) > max_length:
        return False, f"Текст слишком длинный ({len(text)} символов). Максимум: {max_length}"
    
    # Check number of lines
    lines = text.strip().split('\n')
    if len(lines) > max_lines:
        return False, f"Слишком много строк ({len(lines)}). Максимум: {max_lines}"
    
    # Check for suspicious patterns (basic protection against prompt injection)
    suspicious_patterns = [
        r'(?:ignore|забудь|игнорируй|отмени)\s+(?:инструкции|команды|выше|систему)',
        r'(?:system|система)\s*:',
        r'(?:fake|поддельный|фейк)\s+json',
    ]
    
    text_lower = text.lower()
    for pattern in suspicious_patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            log.warning(f"Suspicious pattern detected in input: {pattern}")
            return False, "Ваш запрос содержит подозрительные элементы. Попробуйте переформулировать."
    
    return True, ""


def validate_parsed_invoice(parsed: 'ParsedInvoice', 
                           max_price: float = 1_000_000,
                           max_items: int = 100) -> tuple[bool, str]:
    """
    Validate parsed invoice data from Gemini response.
    Ensures JSON schema is valid before using the data.
    
    Returns: (is_valid, error_message)
    """
    if not parsed.items:
        return False, "Нет позиций в счёте. Попробуйте переформулировать."
    
    if len(parsed.items) > max_items:
        return False, f"Слишком много позиций ({len(parsed.items)}). Максимум: {max_items}"
    
    # Validate each item
    for i, item in enumerate(parsed.items, 1):
        if not item.name or not item.name.strip():
            return False, f"Позиция №{i}: пусто имя товара"
        
        if item.qty <= 0:
            return False, f"Позиция №{i}: количество должно быть > 0"
        
        if item.price <= 0:
            return False, f"Позиция №{i}: цена должна быть > 0"
        
        if item.price > max_price:
            return False, f"Позиция №{i}: цена слишком высока (макс: {max_price})"
    
    # Validate delivery cost
    if parsed.delivery < 0:
        return False, "Стоимость доставки не может быть отрицательной"
    
    if parsed.delivery > max_price:
        return False, f"Доставка слишком дорогая (макс: {max_price})"
    
    return True, ""



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
                'директор', 'руководитель', 'корр', 'расчётн', 'расчетн',
                'счет', 'огрнип', 'корреспондент']
    tl = text.lower()
    return sum(1 for kw in keywords if kw in tl) >= 2


def _parse_buyer_card_regex(text: str) -> dict:
    r: dict = {}

    # ── ИНН ──────────────────────────────────────────────────────
    m = re.search(r'(?:инн)\s*[:/]?\s*(\d{10,12})', text, re.IGNORECASE)
    if m:
        r['inn'] = m.group(1)

    m = re.search(r'(\d{10,12})\s*/\s*(\d{9})', text)
    if m:
        r.setdefault('inn', m.group(1))
        r['kpp'] = m.group(2)

    # ── КПП ──────────────────────────────────────────────────────
    m = re.search(r'кпп\s*[:/]?\s*(\d{9})', text, re.IGNORECASE)
    if m:
        r['kpp'] = m.group(1)

    # ── Р/С (также «Счет:» с 20-значным номером) ─────────────────
    m = re.search(
        r'(?:[рp][/\\][сc]|расч[её]тный\s+сч[её]т|расчетный\s+счет)'
        r'\s*[:\-]?\s*([\d]+)',
        text, re.IGNORECASE
    )
    if m:
        r['rs'] = m.group(1)
    if not r.get('rs'):
        # «Счет:» без уточнения — берём если ровно 20 цифр
        m = re.search(r'\bсчет[:\s]+(\d{20})\b', text, re.IGNORECASE)
        if m:
            r['rs'] = m.group(1)

    # ── БИК ──────────────────────────────────────────────────────
    m = re.search(r'бик\s*[:/]?\s*(\d{9})', text, re.IGNORECASE)
    if m:
        r['bik'] = m.group(1)

    # ── К/С ──────────────────────────────────────────────────────
    m = re.search(
        r'(?:к[/\\]с|корр?\.?\s*сч[её]т|корреспондентский\s+сч[её]т)'
        r'\s*[:\-]?\s*([\d]+)',
        text, re.IGNORECASE
    )
    if m:
        r['ks'] = m.group(1)

    # ── Банк ─────────────────────────────────────────────────────
    m = re.search(r'\bв\s+((?:АО|ПАО|ООО|НКО|Банк)[^\n,]{2,50})', text, re.IGNORECASE)
    if m:
        r['bank_name'] = m.group(1).strip().strip('"')
    if not r.get('bank_name'):
        # «Банк: АО «ТБанк»» — прямой формат
        m = re.search(r'\bбанк[:\s]+((?:АО|ПАО|ООО|НКО|ТБанк|\«)[^\n]{2,60})', text, re.IGNORECASE)
        if m:
            r['bank_name'] = m.group(1).strip().strip('"').strip('«»')

    # ── Наименование (ИП / ООО / АО …) — fallback если Gemini пропустил ──
    if not r.get('name'):
        # Вариант 1: строка целиком начинается с «ИП ФИО» (работает с ALL-CAPS)
        for line in text.splitlines():
            line = line.strip()
            if re.match(r'^ИП\s+\S', line, re.IGNORECASE) and 5 < len(line) < 80:
                r['name'] = line
                break
        # Вариант 2: ООО / АО / ПАО / ЗАО
        if not r.get('name'):
            m = re.search(
                r'\b((?:ООО|ОАО|ПАО|ЗАО|АО|НКО)\s+[«"»\w][^\n,]{2,55})',
                text, re.IGNORECASE
            )
            if m:
                r['name'] = m.group(1).strip().rstrip(' ,;')

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
            'name — полное юридическое наименование с ОПФ '
            '(пример: "ИП Иванов Иван Иванович", "ООО «Ромашка»"). '
            'rs — расчётный счёт (20 цифр), может называться «Счет» или «Р/С». '
            'ks — корреспондентский счёт. '
            'Если поле не найдено — пустая строка.'
        )
        raw = await _gemini_generate(client, prompt, image_bytes=image_bytes)
        return _safe_parse_json(raw)
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
                'Правила:\n'
                '- name — полное юридическое наименование с ОПФ '
                '(пример: "ИП Иванов Иван Иванович", "ООО «Ромашка»"). '
                'Включай ИП/ООО/АО и т.д. в name.\n'
                '- rs — расчётный счёт (20 цифр). '
                'Может называться "Счет", "Р/С", "Расчётный счёт".\n'
                '- ks — корреспондентский счёт (20 цифр).\n'
                '- bank_name — название банка (без адреса и ИНН банка).\n'
                '- Если поле не найдено — пустая строка.\n\n'
                f'Текст:\n{text[:3000]}'
            )
            raw = await _gemini_generate(client, prompt)
            data = _safe_parse_json(raw)
            # Дополняем regex если Gemini что-то пропустил
            regex = _parse_buyer_card_regex(text)
            for k, v in regex.items():
                if not data.get(k):
                    data[k] = v
            if not data.get('name'):
                log.warning("parse_buyer_card: name still empty after Gemini+regex. inn=%s text_start=%r",
                            data.get('inn'), text[:80])
            return data
        except Exception as e:
            log.warning("Gemini buyer card parse error: %s", e)
    return _parse_buyer_card_regex(text)
