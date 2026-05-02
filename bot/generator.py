"""
Генерация пакета документов:
  • Счёт на оплату  (PDF  ← WeasyPrint ← Jinja2/HTML)
  • УПД Статус 1    (PDF  ← WeasyPrint ← Jinja2/HTML)
  • Договор поставки (DOCX ← docxtpl)
  • XML для ЭДО      (XML  ← lxml,  формат ON_NSCHFDOPPR v5.03)
"""
import io
import os
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import jinja2
from weasyprint import HTML as WeasyHTML
from docxtpl import DocxTemplate
from lxml import etree

import config
from num2words_ru import amount_to_words

# ─────────────────────── VAT helpers ──────────────────────────────

_TWO = Decimal('0.01')


def _r(x: Decimal) -> Decimal:
    return x.quantize(_TWO, rounding=ROUND_HALF_UP)


_MONTHS_GEN = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]


def _date_ru(d: date) -> str:
    return f"{d.day} {_MONTHS_GEN[d.month - 1]} {d.year} г."


def _date_short(d: date) -> str:
    return d.strftime('%d.%m.%Y')


def enrich_items(raw_items: list[dict], delivery: Decimal) -> tuple[list[dict], Decimal, Decimal, Decimal]:
    """
    Добавляет к каждому товару: price_without_vat, total_without_vat, vat_amount, total_with_vat.
    Возвращает (enriched_items, total_excl_vat, total_vat, total_incl_vat).
    """
    result = []
    for it in raw_items:
        price_incl  = Decimal(str(it['price']))
        qty         = Decimal(str(it.get('qty', 1)))
        price_excl  = _r(price_incl / (1 + config.VAT_RATE))
        total_incl  = _r(price_incl * qty)
        total_excl  = _r(price_excl * qty)
        vat_amt     = _r(total_incl - total_excl)
        result.append({**it,
                       'price_without_vat': price_excl,
                       'total_without_vat': total_excl,
                       'vat_amount':        vat_amt,
                       'total_with_vat':    total_incl})

    if delivery and delivery > 0:
        d = Decimal(str(delivery))
        d_excl = _r(d / (1 + config.VAT_RATE))
        d_vat  = _r(d - d_excl)
        result.append({
            'name': 'Доставка', 'qty': '', 'unit': 'шт',
            'price': d, 'price_without_vat': d_excl,
            'total_without_vat': d_excl, 'vat_amount': d_vat, 'total_with_vat': d,
        })

    total_excl = _r(sum(i['total_without_vat'] for i in result))
    total_vat  = _r(sum(i['vat_amount']         for i in result))
    total_incl = _r(sum(i['total_with_vat']     for i in result))
    return result, total_excl, total_vat, total_incl


# ─────────────────────── Jinja2 env ───────────────────────────────

def _jinja() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(config.TEMPLATES_DIR),
        autoescape=jinja2.select_autoescape(['html']),
    )
    env.filters['money'] = lambda v: f"{v:,.2f}".replace(',', ' ')
    return env


# ─────────────────────── Invoice PDF ──────────────────────────────

def generate_invoice_pdf(data: dict) -> bytes:
    items, total_excl, total_vat, total_incl = enrich_items(
        data['items'], Decimal(str(data.get('delivery', 0)))
    )
    doc_date     = data['date']
    payment_date = doc_date.replace(day=min(doc_date.day + config.PAYMENT_DAYS, 28))

    html = _jinja().get_template('invoice.html').render(
        doc_number    = data['doc_number'],
        doc_date      = _date_ru(doc_date),
        payment_date  = _date_short(payment_date),
        seller        = config,
        buyer         = data['buyer'],
        items         = items,
        total_excl    = total_excl,
        total_vat     = total_vat,
        total_incl    = total_incl,
        total_words   = amount_to_words(total_incl),
        basis         = data.get('basis', ''),
        item_count    = sum(1 for i in items if i.get('qty') != ''),
    )
    return WeasyHTML(string=html, base_url=config.TEMPLATES_DIR).write_pdf()


# ─────────────────────── UPD PDF ──────────────────────────────────

def generate_upd_pdf(data: dict) -> bytes:
    items, total_excl, total_vat, total_incl = enrich_items(
        data['items'], Decimal(str(data.get('delivery', 0)))
    )
    doc_date = data['date']

    html = _jinja().get_template('upd.html').render(
        doc_number   = data['doc_number'],
        doc_date     = _date_ru(doc_date),
        doc_date_s   = _date_short(doc_date),
        seller       = config,
        buyer        = data['buyer'],
        items        = items,
        total_excl   = total_excl,
        total_vat    = total_vat,
        total_incl   = total_incl,
        vat_label    = config.VAT_LABEL,
    )
    return WeasyHTML(string=html, base_url=config.TEMPLATES_DIR).write_pdf()


# ─────────────────────── Contract PDF ────────────────────────────

def generate_contract_pdf(data: dict) -> bytes:
    items, _, _, total_incl = enrich_items(
        data['items'], Decimal(str(data.get('delivery', 0)))
    )
    doc_date = data['date']
    buyer    = data['buyer']

    items_desc = '; '.join(
        f"{i['name']} ({i['qty']} {i['unit']}) — {i['total_with_vat']:.2f} руб."
        for i in items if i.get('qty') not in ('', None)
    )

    html = _jinja().get_template('contract.html').render(
        doc_number      = data['doc_number'],
        date_day        = doc_date.day,
        date_month      = _MONTHS_GEN[doc_date.month - 1],
        date_year       = doc_date.year,
        contract_end    = f"31 декабря {doc_date.year} г.",
        seller_city     = config.SELLER_CITY,
        buyer_name      = buyer.get('name', ''),
        buyer_inn       = buyer.get('inn', ''),
        buyer_kpp       = buyer.get('kpp', ''),
        buyer_address   = buyer.get('address', ''),
        buyer_director  = buyer.get('director', ''),
        buyer_rs        = buyer.get('rs', ''),
        buyer_bank_name = buyer.get('bank_name', ''),
        buyer_bik       = buyer.get('bik', ''),
        buyer_ks        = buyer.get('ks', ''),
        seller_name     = config.SELLER_NAME,
        seller_inn      = config.SELLER_INN,
        seller_address  = config.SELLER_ADDRESS,
        seller_rs       = config.SELLER_RS,
        seller_bank_name= config.SELLER_BANK_NAME,
        seller_bik      = config.SELLER_BIK,
        seller_ks       = config.SELLER_KS,
        seller_signature= config.SELLER_SIGNATURE,
        items_desc      = items_desc,
        total_amount    = f"{total_incl:.2f}",
        total_words     = amount_to_words(total_incl),
    )
    return WeasyHTML(string=html, base_url=config.TEMPLATES_DIR).write_pdf()


# ─────────────────────── Contract DOCX ────────────────────────────

def generate_contract_docx(data: dict) -> bytes:
    tmpl_path = os.path.join(config.TEMPLATES_DIR, 'contract.docx')
    doc_date = data['date']
    buyer    = data['buyer']

    tpl = DocxTemplate(tmpl_path)
    tpl.render({
        'number':           data['doc_number'],
        'date_day':         doc_date.day,
        'date_month':       _MONTHS_GEN[doc_date.month - 1],
        'date_year':        doc_date.year,
        'buyer_name':       buyer.get('name', ''),
        'buyer_inn':        buyer.get('inn', ''),
        'buyer_kpp':        buyer.get('kpp', ''),
        'buyer_address':    buyer.get('address', ''),
        'buyer_director':   buyer.get('director', ''),
        'buyer_rs':         buyer.get('rs', ''),
        'buyer_bank':       buyer.get('bank_name', ''),
        'buyer_bik':        buyer.get('bik', ''),
        'buyer_ks':         buyer.get('ks', ''),
        'contract_end':     f"31 декабря {doc_date.year} г.",
    })
    buf = io.BytesIO()
    tpl.save(buf)
    return buf.getvalue()


# ─────────────────────── EDO XML ──────────────────────────────────

def generate_xml(data: dict) -> bytes:
    """Генерирует XML-файл УПД в формате ФНС ON_NSCHFDOPPR v5.03 (windows-1251).
    Структура соответствует выгрузке 1С:Предприятие 8."""
    items, total_excl, total_vat, total_incl = enrich_items(
        data['items'], Decimal(str(data.get('delivery', 0)))
    )
    doc_date = data['date']
    buyer    = data['buyer']
    num_raw  = data['doc_number']
    num_int  = ''.join(c for c in num_raw if c.isdigit()) or num_raw

    doc_uuid = str(uuid.uuid4())
    file_id = (
        f"ON_NSCHFDOPPR_{buyer.get('inn','')}_"
        f"{buyer.get('kpp','')}_{config.SELLER_INN}_"
        f"{doc_date.strftime('%Y%m%d')}_{doc_uuid[:8]}"
    )
    basis_uuid = str(uuid.uuid4())

    NSMAP = {
        'xs':  'http://www.w3.org/2001/XMLSchema',
        'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
    }

    root = etree.Element('Файл', nsmap=NSMAP)
    root.set('ИдФайл',  file_id)
    root.set('ВерсФорм', '5.03')
    root.set('ВерсПрог', '1С:Предприятие 8')

    doc_el = etree.SubElement(root, 'Документ')
    doc_el.set('КНД',            '1115131')
    doc_el.set('Функция',        'СЧФДОП')
    doc_el.set('ПоФактХЖ',
               'Документ об отгрузке товаров (выполнении работ), '
               'передаче имущественных прав (документ об оказании услуг)')
    doc_el.set('НаимДокОпр',     'Универсальный передаточный документ')
    doc_el.set('ДатаИнфПр',      _date_short(doc_date))
    doc_el.set('ВремИнфПр',      datetime.now().strftime('%H.%M.%S'))
    doc_el.set('НаимЭконСубСост',
               f'ИП {config.SELLER_SHORT_NAME}, ИНН {config.SELLER_INN}')

    # ── СвСчФакт ──
    sv = etree.SubElement(doc_el, 'СвСчФакт')
    sv.set('НомерДок', num_int)
    sv.set('ДатаДок',  _date_short(doc_date))

    # Продавец
    sv_prod = etree.SubElement(sv, 'СвПрод')
    id_sv   = etree.SubElement(sv_prod, 'ИдСв')
    sv_ip   = etree.SubElement(id_sv, 'СвИП')
    sv_ip.set('ИННФЛ',        config.SELLER_INN)
    sv_ip.set('СвГосРегИП',
              f'ОГРНИП {config.SELLER_OGRNIP}, '
              f'дата регистрации {config.SELLER_OGRNIP_DATE_FULL}')
    sv_ip.set('ОГРНИП',       config.SELLER_OGRNIP)
    sv_ip.set('ДатаОГРНИП',   config.SELLER_OGRNIP_DATE)
    fio = etree.SubElement(sv_ip, 'ФИО')
    fio.set('Фамилия',  'Шавкова')
    fio.set('Имя',      'Тамара')
    fio.set('Отчество', 'Расуловна')

    adr_prod = etree.SubElement(sv_prod, 'Адрес')
    adr_gar  = etree.SubElement(adr_prod, 'АдрГАР')
    adr_gar.set('ИдНом',  '6fec9385-d53d-493f-95cc-760898426c4c')
    adr_gar.set('Индекс', '358004')
    etree.SubElement(adr_gar, 'Регион').text        = config.SELLER_ADDR_REGION_CODE
    etree.SubElement(adr_gar, 'НаимРегион').text     = config.SELLER_ADDR_REGION_NAME
    mun = etree.SubElement(adr_gar, 'МуниципРайон')
    mun.set('ВидКод', '2'); mun.set('Наим', 'город Элиста')
    nas = etree.SubElement(adr_gar, 'НаселенПункт')
    nas.set('Вид', 'г.'); nas.set('Наим', 'Элиста')
    ul = etree.SubElement(adr_gar, 'ЭлУлДорСети')
    ul.set('Тип', 'пр-д'); ul.set('Наим', 'Автомобилистов 3-й')
    zd = etree.SubElement(adr_gar, 'Здание')
    zd.set('Тип', 'д.'); zd.set('Номер', '1')

    rekv = etree.SubElement(sv_prod, 'БанкРекв')
    rekv.set('НомерСчета', config.SELLER_RS)
    bank_el = etree.SubElement(rekv, 'СвБанк')
    bank_el.set('НаимБанк', config.SELLER_BANK_NAME)
    bank_el.set('БИК',      config.SELLER_BIK)
    bank_el.set('КорСчет',  config.SELLER_KS)

    # Грузоотправитель (он же)
    gruz_ot = etree.SubElement(sv, 'ГрузОт')
    etree.SubElement(gruz_ot, 'ОнЖе').text = 'он же'

    # Грузополучатель
    gruz_pol = etree.SubElement(sv, 'ГрузПолуч')
    gp_id    = etree.SubElement(gruz_pol, 'ИдСв')
    gp_yul   = etree.SubElement(gp_id, 'СвЮЛУч')
    gp_yul.set('НаимОрг', buyer.get('name', ''))
    gp_yul.set('ИННЮЛ',   buyer.get('inn', ''))
    if buyer.get('kpp'):
        gp_yul.set('КПП', buyer['kpp'])
    gp_adr   = etree.SubElement(gruz_pol, 'Адрес')
    gp_ainf  = etree.SubElement(gp_adr, 'АдрИнф')
    gp_ainf.set('КодСтр',   '643')
    gp_ainf.set('НаимСтран', 'РОССИЯ')
    gp_ainf.set('АдрТекст', buyer.get('address', ''))

    # ДокПодтвОтгрНом
    dpod = etree.SubElement(sv, 'ДокПодтвОтгрНом')
    dpod.set('РеквНаимДок',  'Универсальный передаточный документ')
    dpod.set('РеквНомерДок', num_int)
    dpod.set('РеквДатаДок',  _date_short(doc_date))

    # Покупатель
    sv_pok   = etree.SubElement(sv, 'СвПокуп')
    pok_id   = etree.SubElement(sv_pok, 'ИдСв')
    pok_yul  = etree.SubElement(pok_id, 'СвЮЛУч')
    pok_yul.set('НаимОрг', buyer.get('name', ''))
    pok_yul.set('ИННЮЛ',   buyer.get('inn', ''))
    if buyer.get('kpp'):
        pok_yul.set('КПП', buyer['kpp'])
    pok_adr  = etree.SubElement(sv_pok, 'Адрес')
    pok_ainf = etree.SubElement(pok_adr, 'АдрИнф')
    pok_ainf.set('КодСтр',   '643')
    pok_ainf.set('НаимСтран', 'РОССИЯ')
    pok_ainf.set('АдрТекст', buyer.get('address', ''))

    # Валюта
    den = etree.SubElement(sv, 'ДенИзм')
    den.set('КодОКВ',  '643')
    den.set('НаимОКВ', 'Российский рубль')
    den.set('КурсВал', '1.00')

    # ИнфПолФХЖ1
    inf1 = etree.SubElement(sv, 'ИнфПолФХЖ1')
    for ident, val in [
        ('ИдентификаторДокументаОснования', basis_uuid),
        ('ВидСчетаФактуры', 'Реализация'),
        ('ТолькоУслуги', 'false'),
        ('ДокументОбОтгрузке',
         f'№ п/п 1 № {num_int} от {_date_short(doc_date)} г.'),
    ]:
        ti = etree.SubElement(inf1, 'ТекстИнф')
        ti.set('Идентиф', ident)
        ti.set('Значен', val)

    # ── ТаблСчФакт ──
    total_qty = 0
    tabl = etree.SubElement(doc_el, 'ТаблСчФакт')
    for idx, it in enumerate(items, 1):
        st = etree.SubElement(tabl, 'СведТов')
        st.set('НомСтр',      str(idx))
        st.set('НаимТов',     it['name'])
        qty_val = it.get('qty')
        if qty_val not in ('', None):
            st.set('ОКЕИ_Тов', '796')
            st.set('НаимЕдИзм', str(it.get('unit', 'шт')))
            st.set('КолТов',   str(qty_val))
            st.set('ЦенаТов',  f"{it['price_without_vat']:.2f}")
            total_qty += int(qty_val) if str(qty_val).isdigit() else 1
        st.set('СтТовБезНДС', f"{it['total_without_vat']:.2f}")
        st.set('НалСт',        config.VAT_LABEL)
        st.set('СтТовУчНал',  f"{it['total_with_vat']:.2f}")

        dop_sv = etree.SubElement(st, 'ДопСведТов')
        dop_sv.set('ПрТовРаб', str(idx))

        ak = etree.SubElement(st, 'Акциз')
        etree.SubElement(ak, 'БезАкциз').text = 'без акциза'

        nds_el = etree.SubElement(st, 'СумНал')
        etree.SubElement(nds_el, 'СумНал').text = f"{it['vat_amount']:.2f}"

        item_uuid = str(uuid.uuid4())
        for ident, val in [
            ('Для1С_Идентификатор', f'{item_uuid}##'),
            ('Для1С_Наименование', it['name']),
            ('Для1С_ЕдиницаИзмерения', str(it.get('unit', 'шт'))),
            ('Для1С_ЕдиницаИзмеренияКод', '796'),
            ('Для1С_СтавкаНДС', '5'),
            ('ИД', f'{item_uuid}##'),
        ]:
            inf2 = etree.SubElement(st, 'ИнфПолФХЖ2')
            inf2.set('Идентиф', ident)
            inf2.set('Значен', val)

    vsego = etree.SubElement(tabl, 'ВсегоОпл')
    vsego.set('СтТовБезНДСВсего', f"{total_excl:.2f}")
    vsego.set('СтТовУчНалВсего',  f"{total_incl:.2f}")
    vsego.set('КолНеттоВс',       str(total_qty))
    nds_v = etree.SubElement(vsego, 'СумНалВсего')
    etree.SubElement(nds_v, 'СумНал').text = f"{total_vat:.2f}"

    # ── СвПродПер ──
    sv_pp = etree.SubElement(doc_el, 'СвПродПер')
    sv_per = etree.SubElement(sv_pp, 'СвПер')
    sv_per.set('СодОпер', 'Товары переданы')
    sv_per.set('ВидОпер', 'Продажа')
    sv_per.set('ДатаПер', _date_short(doc_date))
    etree.SubElement(sv_per, 'БезДокОснПер').text = '1'

    inf3 = etree.SubElement(sv_pp, 'ИнфПолФХЖ3')
    ti3  = etree.SubElement(inf3, 'ТекстИнф')
    ti3.set('Идентиф', 'ИдентификаторДокументаОснования')
    ti3.set('Значен',  basis_uuid)

    # ── Подписант ──
    podp = etree.SubElement(doc_el, 'Подписант')
    podp.set('ТипПодпис', '2')
    podp.set('СпосПодтПолном', '1')
    fio2 = etree.SubElement(podp, 'ФИО')
    fio2.set('Фамилия', '-')
    fio2.set('Имя',     '-')

    return etree.tostring(
        root,
        encoding='windows-1251',
        xml_declaration=True,
        pretty_print=True,
    )
