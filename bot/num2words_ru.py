"""
Преобразование числовых сумм в текст на русском языке.
Пример: Decimal('32940.00') → 'Тридцать две тысячи девятьсот сорок рублей 00 копеек'
"""
from decimal import Decimal

_ONES_M = [
    '', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять',
    'десять', 'одиннадцать', 'двенадцать', 'тринадцать', 'четырнадцать', 'пятнадцать',
    'шестнадцать', 'семнадцать', 'восемнадцать', 'девятнадцать',
]
_ONES_F = [
    '', 'одна', 'две', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять',
    'десять', 'одиннадцать', 'двенадцать', 'тринадцать', 'четырнадцать', 'пятнадцать',
    'шестнадцать', 'семнадцать', 'восемнадцать', 'девятнадцать',
]
_TENS = [
    '', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят',
    'шестьдесят', 'семьдесят', 'восемьдесят', 'девяносто',
]
_HUNDREDS = [
    '', 'сто', 'двести', 'триста', 'четыреста', 'пятьсот',
    'шестьсот', 'семьсот', 'восемьсот', 'девятьсот',
]


def _plural(n: int, one: str, two: str, five: str) -> str:
    n = abs(n) % 100
    if 10 <= n <= 20:
        return five
    n = n % 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return two
    return five


def _chunk(n: int, feminine: bool = False) -> str:
    """Преобразует число 1–999 в слова."""
    if not n:
        return ''
    parts = []
    h = n // 100
    if h:
        parts.append(_HUNDREDS[h])
    rem = n % 100
    if rem < 20:
        w = (_ONES_F if feminine else _ONES_M)[rem]
        if w:
            parts.append(w)
    else:
        t, o = rem // 10, rem % 10
        if t:
            parts.append(_TENS[t])
        if o:
            w = (_ONES_F if feminine else _ONES_M)[o]
            if w:
                parts.append(w)
    return ' '.join(parts)


def number_to_words(n: int, feminine: bool = False) -> str:
    if n == 0:
        return 'ноль'
    parts = []
    billions = n // 1_000_000_000
    if billions:
        parts.append(f"{_chunk(billions)} {_plural(billions, 'миллиард', 'миллиарда', 'миллиардов')}")
        n %= 1_000_000_000
    millions = n // 1_000_000
    if millions:
        parts.append(f"{_chunk(millions)} {_plural(millions, 'миллион', 'миллиона', 'миллионов')}")
        n %= 1_000_000
    thousands = n // 1_000
    if thousands:
        parts.append(f"{_chunk(thousands, feminine=True)} {_plural(thousands, 'тысяча', 'тысячи', 'тысяч')}")
        n %= 1_000
    if n:
        w = _chunk(n, feminine=feminine)
        if w:
            parts.append(w)
    return ' '.join(p.strip() for p in parts if p.strip())


def amount_to_words(amount: Decimal) -> str:
    """
    32940.00 → 'Тридцать две тысячи девятьсот сорок рублей 00 копеек'
    """
    amount = Decimal(str(amount)).quantize(Decimal('0.01'))
    rubles = int(amount)
    kopeks = int(round((amount - rubles) * 100))
    rub_words = number_to_words(rubles, feminine=False)
    rub_form  = _plural(rubles, 'рубль', 'рубля', 'рублей')
    return f"{rub_words.capitalize()} {rub_form} {kopeks:02d} копеек"
