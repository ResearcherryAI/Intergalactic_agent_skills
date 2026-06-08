#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
money_validate.py — жёсткий гейт-валидатор разбора ДНК денег.

Запуск ОБЯЗАТЕЛЕН перед показом разбора Дарье.
Пока есть хоть один [FAIL] — показывать файл ЗАПРЕЩЕНО.

Использование (из корня Producty):
    python .cursor/skills/2-money-analysis/money_validate.py "<путь к *_деньги.md>"

Жёсткие проверки по нюансам карты (добавлено 03.06.2026):
    A. Диспозиторы Раху/Кету расшифрованы с практическим действием (FAIL)
    B. Объединяющая флагман-профессия перед 11 сферами (FAIL)
    C. 11 сфер разбиты на 3 пласта (материальные/эзотерические/масштабные) (FAIL)
    D. Аттрактор на Асценденте → обязательная тень «притяжение без фильтра» (FAIL)
    E. Сторож достоинства: Марс/Луна в Раке не описаны вопреки падению (WARN)
    F. Нет «урока джйотиш» (управитель/божество/символ накшатры) в тексте (FAIL)
    G. Наставничество не перегружено (>3 упоминаний) (WARN)

Корневые принципы (Дарья, 07.06.2026, разбор Марты):
    S. Орб в тексте обязан совпадать с картой (CSV) (FAIL)
    T. Своё соединение раздела раскрыто как цивилизация (FAIL)
    U. Энергодуш стоит по смыслу, а не «прибит» к Сатурну (FAIL)
    V. Достаточно конкретных профессий, в т.ч. в 11 сферах (WARN)
    W. Стеллиумы (2+ планеты в доме) описаны как взаимосвязь, не по одиночке (FAIL)
"""
import re
import sys
import io

# гарантируем utf-8 вывод в Windows-консоли
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Эталонный порядок H2-разделов (после устранения конфликта practices/support)
EXPECTED_ORDER = [
    "АСЦЕНДЕНТ",
    "ЮПИТЕР",
    "САТУРН",
    "2-й ДОМ",
    "11-й ДОМ",
    "РАХУ И КЕТУ",
    "СОЛНЦЕ",
    "ЛУНА",
    "ОСОБЫЕ ПОКАЗАТЕЛИ БОГАТСТВА",
    "ДЕНЕЖНЫЙ АРХЕТИП",
    "ПОМОЩНИК В ДЕНЬГАХ",
    "ВОЗРАСТЫ ФИНАНСОВОГО ПРОРЫВА",
    "11 СФЕР МАКСИМАЛЬНЫХ ДЕНЕГ",
    "ПРАКТИКИ",
    "5 ГЛАВНЫХ СИЛ И 5 ГЛАВНЫХ ТЕНЕЙ",
    "СОПРОВОЖДЕНИЕ",
]

# Запрещённые местоимения третьего лица о КЛИЕНТЕ (текст — только на «вы»).
# «её/ей/оно» исключены: это грамматика неодушевлённых (миссия, Солнце, звезда).
THIRD_PERSON = [
    r"\bона\b", r"\bу неё\b", r"\bей,",
    r"\bженщина\b", r"\bженщины\b", r"\bженщине\b", r"\bженщину\b",
    r"\bженщиной\b", r"\bэта женщина\b", r"\bносительница\b", r"\bгероиня\b",
]

# Джйотиш-жаргон и астрожаргон, запрещённый в клиентском тексте
JARGON = [
    r"\bйог[аиу]\b", r"\bйоги\b", r"\bкарак[аи]\b", r"\bкендр[аы]\b",
    r"\bтрикон[аы]\b", r"\bдустхан[аы]\b", r"\bмарак[аи]\b", r"\bбадхак[аи]\b",
    r"\bупачай[аи]\b", r"экзальтац", r"дебилитац", r"мулатрикон",
    r"варготтам", r"диг-бал", r"навамш", r"грaha", r"graha",
    r"Гаджа-кешари", r"Дхана-йог", r"Раджа-йог", r"Хамса-йог",
    r"Панча-Махапуруша", r"Випарита",
]

# ── Корневые принципы (Дарья, 07.06.2026) ───────────────────────────
# 1. Выдумывание: запрещены любые придуманные/неверные термины.
#    «астероид» — звёзды и цивилизации не астероиды; самодельные
#    дефисные аспект-существительные («астероид-трин») тоже запрещены.
FABRICATED = [
    r"астероид\w*",
    r"\bквазар\w*",
    r"\bметеорит\w*",
]
COMPOUND_ASPECT = r"[А-Яа-яё]{3,}-(?:трин|секстил|квадрат|оппозици|соединени)\w*"

# 2. Своя «кухня»: запрещены расчёты, формулы и собственные рассуждения
#    агента в клиентском тексте. Аспект описываем словами, без чисел.
CALC_PATTERNS = [
    r"\d+\s*[+\-]\s*\d+\s*=",     # 7+1=8, 9-3=6
    r"=\s*H\s*\d+",              # = H14
    r"H\d+\s*[+\-]\s*\d+",        # H6+9
    r"по\s+формуле",
    r"значит\s+аспект",
]
META_PATTERNS = [
    r"уместно\s+упомянуть",
    r"здесь\s+важно\s+упомянуть",
    r"в\s+этом\s+разделе\s+уместн",
    r"стоит\s+отметить",
    r"как\s+договорились",
    r"следуя\s+эталону",
    r"для\s+удобства",
    r"как\s+принято\s+в",
    r"соединени\w*\s+(?:всегда\s+)?сильнее",
    r"сильнее\s+(?:любого\s+)?аспект",
    r"приоритетнее\s+(?:трин|аспект)",
    r"не\s+главн\w+\s+(?:денежн|финансов)\w*\s+(?:сил|звезд|показател)",
    r"это\s+главн\w+\s+(?:денежн|финансов)\w*\s+(?:сил|звезд|показател)",
]

# 3. Копипаст вместо анализа: «образование/курс» нельзя совать в каждую
#    карту. Семья слов + потолки.
FORMAT_FAMILY = r"курс\w*|образован\w*|обучающ\w*|образовательн\w*|учебн\w*"
FORMAT_GLOBAL_CAP = 6      # всего по файлу
FORMAT_SPHERES_CAP = 3     # сколько из 11 сфер могут касаться образования

# Услуги-ссылки для проверки «1 услуга на раздел» (WhatsApp-CTA не услуга).
SERVICE_ANCHORS = [
    "cleansing-202", "consultation-508", "/book/", "#mission", "mentorship-6130",
]

# Белый список цивилизаций/точек (дополняет имена из CSV клиента).
CIV_ALLOW = {
    "орион", "гиады", "гиадум", "малый пёс", "большой пёс", "кит", "андромеда",
    "лира", "вега", "центавр", "кентавр", "лев", "дева", "телец", "скорпион",
    "плеяды", "кассиопея", "возничий", "орёл", "заяц", "гидра", "южная рыба",
    "дракон", "волопас", "близнецы", "рак", "весы", "стрелец", "водолей",
    "овен", "рыбы", "козерог", "галактический центр", "сверх-галактический центр",
    "великий аттрактор", "аттрактор шепли", "полярная", "большая медведица",
    "туманность ориона", "кольцо лиры",
}

# Планеты для детекции стеллиумов (W). Ключ — имя в CSV, значение — стем,
# ловящий падежи в тексте («Венер» = Венера/Венеры/Венере).
PLANET_STEMS = {
    "Солнце": "Солн", "Луна": "Лун", "Меркурий": "Мерк", "Венера": "Венер",
    "Марс": "Марс", "Юпитер": "Юпит", "Сатурн": "Сатур", "Раху": "Раху",
    "Кету": "Кету", "Уран": "Уран", "Нептун": "Непт", "Плутон": "Плут",
}
# Слова-связки: признак синтеза взаимосвязи планет, а не описания по одиночке.
CONNECT_WORDS = (
    r"вместе|в\s+связк|единой?\s+связк|единым\s+узлом|стеллиум|усилива|"
    r"дополня|влия\w+\s+на|поддержива|взаимодейств|в\s+паре|сообща|"
    r"друг\s+друг|совместн|одной\s+командой|работа\w+\s+(?:в\s+)?связк"
)

results = []  # (level, message)


def add(level, msg):
    results.append((level, msg))


def check_third_person(text_no_quotes):
    hits = []
    for pat in THIRD_PERSON:
        for m in re.finditer(pat, text_no_quotes, flags=re.IGNORECASE):
            hits.append(m.group(0))
    if hits:
        uniq = sorted(set(h.lower() for h in hits))
        add("FAIL", f"Местоимения 3-го лица ({len(hits)} шт.): {', '.join(uniq)} — заменить на «вы/ваш».")
    else:
        add("PASS", "Нет местоимений 3-го лица (текст на «вы»).")


def check_jargon(text):
    hits = []
    for pat in JARGON:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            hits.append(m.group(0))
    if hits:
        uniq = sorted(set(h.lower() for h in hits))
        add("FAIL", f"Джйотиш/астро-жаргон: {', '.join(uniq)} — убрать или объяснить простым языком.")
    else:
        add("PASS", "Нет запрещённого джйотиш-жаргона.")


def check_latin_in_cyrillic(text):
    # слова, где смешаны кириллица и латиница (типичная ошибка: Рахu, Юпiter)
    bad = re.findall(r"\b[А-Яа-яЁё]+[A-Za-z]+[А-Яа-яЁё]*\b|\b[A-Za-z]+[А-Яа-яЁё]+[A-Za-z]*\b", text)
    # отфильтровать допустимые латинские обозначения звёзд (M42, M57) и проценты
    bad = [b for b in bad if not re.fullmatch(r"[Mм]\d+", b)]
    if bad:
        add("FAIL", f"Латиница внутри кириллицы: {', '.join(sorted(set(bad))[:10])}")
    else:
        add("PASS", "Нет смешанных кириллица+латиница слов.")


def get_h2_sections(text):
    return re.findall(r"^##\s+(?:\d+\.\s+)?(.+?)\s*$", text, flags=re.MULTILINE)


def check_order(text):
    sections = get_h2_sections(text)
    # нормализуем: берём ядро заголовка до тире
    norm = []
    for s in sections:
        core = s.split("—")[0].strip()
        norm.append(core)
    seq = [s for s in norm if any(s.startswith(e) for e in EXPECTED_ORDER)]
    # сопоставляем порядок
    found_order = []
    for s in seq:
        for e in EXPECTED_ORDER:
            if s.startswith(e):
                found_order.append(e)
                break
    # проверяем, что found_order — подпоследовательность EXPECTED_ORDER в правильном порядке
    idx = 0
    ok = True
    for f in found_order:
        while idx < len(EXPECTED_ORDER) and EXPECTED_ORDER[idx] != f:
            idx += 1
        if idx >= len(EXPECTED_ORDER):
            ok = False
            break
        idx += 1
    missing = [e for e in EXPECTED_ORDER if e not in found_order]
    if not ok:
        add("FAIL", f"Порядок разделов нарушен. Найдено: {found_order}")
    elif missing:
        add("FAIL", f"Отсутствуют разделы: {', '.join(missing)}")
    else:
        add("PASS", "Все разделы на месте и в правильном порядке.")

    # практики ДО сопровождения, сопровождение последнее
    if "ПРАКТИКИ" in found_order and "СОПРОВОЖДЕНИЕ" in found_order:
        if found_order.index("ПРАКТИКИ") < found_order.index("СОПРОВОЖДЕНИЕ"):
            add("PASS", "ПРАКТИКИ идут до СОПРОВОЖДЕНИЯ (Сопровождение последнее).")
        else:
            add("FAIL", "ПРАКТИКИ стоят после СОПРОВОЖДЕНИЯ — переставить: Сопровождение должно быть последним блоком.")

    # 5 сил и 5 теней — ВСЕГДА прямо перед СОПРОВОЖДЕНИЕМ (в самом конце)
    if "5 ГЛАВНЫХ СИЛ И 5 ГЛАВНЫХ ТЕНЕЙ" in found_order and "СОПРОВОЖДЕНИЕ" in found_order:
        si = found_order.index("5 ГЛАВНЫХ СИЛ И 5 ГЛАВНЫХ ТЕНЕЙ")
        ci = found_order.index("СОПРОВОЖДЕНИЕ")
        if si == ci - 1:
            add("PASS", "5 СИЛ И 5 ТЕНЕЙ стоят прямо перед СОПРОВОЖДЕНИЕМ.")
        else:
            add("FAIL", "5 СИЛ И 5 ТЕНЕЙ должны стоять прямо перед СОПРОВОЖДЕНИЕМ (тени всегда в самом конце, после практик).")


def check_spheres(text):
    m = re.search(r"##\s+11 СФЕР.*?(?=\n##\s)", text, flags=re.DOTALL)
    if not m:
        add("FAIL", "Раздел «11 сфер максимальных денег» не найден.")
        return
    block = m.group(0)
    nums = re.findall(r"^\s*(\d+)\.\s+\*\*", block, flags=re.MULTILINE)
    count = len(nums)
    if count == 11:
        add("PASS", "Ровно 11 сфер.")
    else:
        add("FAIL", f"Сфер должно быть 11, найдено {count}.")
    # «Через год» в каждой сфере
    year_markers = len(re.findall(r"[Чч]ерез год", block))
    if year_markers >= 11:
        add("PASS", f"Маркер «Через год» присутствует ({year_markers}).")
    else:
        add("FAIL", f"Маркер «Через год» найден {year_markers} раз, нужно в каждой из 11 сфер.")


def check_practices(text):
    m = re.search(r"##\s+ПРАКТИКИ.*?(?=\n##\s|\Z)", text, flags=re.DOTALL)
    if not m:
        add("FAIL", "Раздел «ПРАКТИКИ» не найден.")
        return
    block = m.group(0)
    subs = re.findall(r"^###\s+", block, flags=re.MULTILINE)
    if len(subs) == 2:
        add("PASS", "Ровно 2 практики.")
    else:
        add("FAIL", f"Практик должно быть 2, найдено {len(subs)}.")


def check_links(text):
    services = {
        "Энергодуш": "cleansing-202",
        "Консультация": "consultation-508",
        "Книга": "/book/",
        "Миссия": "#mission",
        "Сопровождение": "mentorship-6130",
    }
    found = {name: text.count(anchor) for name, anchor in services.items()}
    missing = [n for n, c in found.items() if c == 0]
    dup = [n for n, c in found.items() if c > 1]
    if not missing and not dup:
        add("PASS", "Все 5 сервисных ссылок присутствуют по 1 разу.")
    else:
        msg = ""
        if missing:
            msg += f"отсутствуют: {', '.join(missing)}. "
        if dup:
            msg += f"дублируются: {', '.join(dup)}."
        add("FAIL", f"Ссылки: {msg}")


def check_energodush_meaning(text):
    """U. Энергодуш ставится ПО СМЫСЛУ — там, где речь о чистке/чужих
    программах/поглощении/токсичном, а не прибивается к Сатурну.
    (Установлено Дарьей 07.06.2026 на разборе Марты.)"""
    if "cleansing-202" not in text:
        add("FAIL", "U. Ссылка на Энергодуш не найдена.")
        return
    for h, b in split_sections(text):
        if "cleansing-202" not in b:
            continue
        if re.search(r"чист|очищ|токсич|чуж\w|поглощ|налип|освобо|програм", b, flags=re.IGNORECASE):
            add("PASS", "U. Энергодуш стоит по смыслу (чистка/чужое/токсичное/поглощение).")
        else:
            add("FAIL", f"U. Энергодуш в разделе «{h.lstrip('# ').strip()[:24]}» не по смыслу — ставить там, где речь о чистке/чужих программах/поглощении, а не «привязывать» к планете.")
        return


def check_civilizations(text):
    # ТОП-3 цивилизации: ≥3 блока «СПОСОБ МАТЕРИАЛИЗАЦИИ», и перед каждым
    # должно быть подробное описание существ (≥4 предложений).
    positions = [m.start() for m in re.finditer(r"СПОСОБ МАТЕРИАЛИЗАЦИИ", text)]
    if len(positions) < 3:
        add("FAIL", f"Блоков «СПОСОБ МАТЕРИАЛИЗАЦИИ» = {len(positions)} — нужно ≥3 (ТОП-3 цивилизации).")
        return
    thin = 0
    for pos in positions:
        before = text[max(0, pos - 900):pos]
        # последний абзац перед СПОСОБ МАТЕРИАЛИЗАЦИИ = описание существ
        para = before.split("\n\n")[-2] if "\n\n" in before.strip() else before
        sentences = len(re.findall(r"[.!?]", para))
        if sentences < 4:
            thin += 1
    if thin == 0:
        add("PASS", f"ТОП-3 цивилизации: {len(positions)} блоков, описание существ ≥4 предложений у каждого.")
    else:
        add("FAIL", f"У {thin} цивилизаций описание существ короче 4 предложений — расширить до 5-6.")


def check_abstractions(text):
    # ловим типичные абстракции без денежного смысла
    abstr = []
    for pat in [r"фундамент сначала", r"надстройк[аи] потом", r"строится как дом"]:
        if re.search(pat, text, flags=re.IGNORECASE):
            abstr.append(pat)
    if abstr:
        add("WARN", f"Возможные абстракции без денежного смысла: {abstr} — заменить на конкретику (что с деньгами, как зарабатываете).")
    else:
        add("PASS", "Явных абстракций-штампов не найдено.")


# ── Разбиение на H2-секции (ровно два #, со следующим пробелом) ──────
def split_sections(text):
    """Возвращает список (heading, body) по H2-заголовкам (## ...).
    ### подзаголовки не считаются за секцию."""
    parts = re.split(r"(?m)^(##\s[^\n]*)$", text)
    sections = []
    i = 1
    while i < len(parts):
        heading = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections.append((heading, body))
        i += 2
    return sections


def find_section(sections, keyword):
    for h, b in sections:
        if keyword in h.upper():
            return h, b
    return None, None


def get_spheres_block(text):
    m = re.search(r"##\s+11 СФЕР.*?(?=\n##\s|\Z)", text, flags=re.DOTALL)
    return m.group(0) if m else ""


# ── A. Диспозиторы Раху/Кету + практическое действие ────────────────
def check_dispositors(sections):
    _, b = find_section(sections, "РАХУ")
    if not b:
        add("FAIL", "A. Раздел «РАХУ И КЕТУ» не найден — диспозиторы не проверить.")
        return
    has_rahu = re.search(r"диспозитор\w*\s+раху", b, flags=re.IGNORECASE) is not None
    has_ketu = re.search(r"диспозитор\w*\s+кету", b, flags=re.IGNORECASE) is not None
    action = re.search(
        r"(иди\w*|пойт\w*|сделайт\w*|что сделать|куда пойти|оформит\w*|выходит\w*|покажит\w*)",
        b, flags=re.IGNORECASE,
    ) is not None
    if has_rahu and has_ketu and action:
        add("PASS", "A. Диспозиторы Раху и Кету расшифрованы с практическим действием.")
    else:
        miss = []
        if not has_rahu:
            miss.append("нет «диспозитор Раху»")
        if not has_ketu:
            miss.append("нет «диспозитор Кету»")
        if not action:
            miss.append("нет практического действия (куда пойти / что сделать)")
        add("FAIL", f"A. Раху/Кету: {'; '.join(miss)} — добавить расшифровку диспозиторов с конкретикой.")


# ── B. Флагман-профессия перед 11 сферами ───────────────────────────
def check_flagship(text):
    block = get_spheres_block(text)
    if not block:
        return  # отсутствие раздела ловит check_spheres
    m = re.search(r"профессия,?\s+(?:в которой|объединяющ)", block, flags=re.IGNORECASE)
    if not m:
        add("FAIL", "B. Нет объединяющей флагман-профессии («**Профессия, в которой всё сходится…**») в конце блока 11 сфер.")
        return
    # флагман-профессия должна стоять ПОСЛЕ 11-й сферы (как итог, в конце блока)
    last_sphere = None
    for sm in re.finditer(r"^\s*11\.\s+\*\*", block, flags=re.MULTILINE):
        last_sphere = sm.start()
    if last_sphere is not None and m.start() > last_sphere:
        add("PASS", "B. Флагман-профессия стоит в конце 11 сфер (итог-вишенка).")
    else:
        add("FAIL", "B. Флагман-профессия должна стоять в КОНЦЕ 11 сфер (после 11-й сферы), а не в начале.")


# ── C. Три пласта в 11 сферах ───────────────────────────────────────
def check_sphere_layers(text):
    block = get_spheres_block(text)
    if not block:
        return
    layers = []
    if re.search(r"материальн", block, flags=re.IGNORECASE):
        layers.append("материальные")
    if re.search(r"эзотерическ", block, flags=re.IGNORECASE):
        layers.append("эзотерические")
    if re.search(r"масштабн", block, flags=re.IGNORECASE):
        layers.append("масштабные")
    if len(layers) == 3:
        add("PASS", "C. 11 сфер разбиты на 3 пласта (материальные / эзотерические / масштабные).")
    else:
        add("FAIL", f"C. В 11 сферах не хватает деления на 3 пласта (найдено: {layers or 'ничего'}).")


# ── D. Аттрактор на Асценденте = минус «притяжение без фильтра» ──────
def check_attractor_filter(sections):
    _, b = find_section(sections, "АСЦЕНДЕНТ")
    if not b:
        return
    if "аттрактор" not in b.lower() and "шепли" not in b.lower():
        add("PASS", "D. Сильный аттрактор на Асценденте не обнаружен — проверка не применима.")
        return
    if re.search(r"(кого попало|чётк\w*\s+запрос|без фильтра|\bфильтр)", b, flags=re.IGNORECASE):
        add("PASS", "D. Аттрактор на Асценденте: тень «притяжение без фильтра» присутствует.")
    else:
        add("FAIL", "D. Аттрактор на Асценденте есть, но нет тени «притяжение без фильтра» (кого попало / чёткий запрос).")


# ── E. Сторож достоинства (падение Марса/Луны в Раке) ───────────────
def _non_negated(text, pattern):
    """True, если есть вхождение pattern БЕЗ предшествующего «не » (в ~20 симв.)."""
    for m in re.finditer(pattern, text, flags=re.IGNORECASE):
        pre = text[max(0, m.start() - 20):m.start()].lower()
        if not re.search(r"\bне\s+\S*$|\bне\s+$", pre):
            return True
    return False


def check_dignity(text):
    issues = []
    if re.search(r"Марс\s+в\s+Раке", text, flags=re.IGNORECASE):
        if _non_negated(text, r"дожиматель|жёстк\w*\s+переговор|жёсткий\s+дожим"):
            issues.append("Марс в Раке (падение) описан как «жёсткий дожиматель/переговорщик»")
    if re.search(r"Луна\s+в\s+Раке", text, flags=re.IGNORECASE):
        if _non_negated(text, r"счита\w*\s+и\s+удержив|учит\w*\s+счита"):
            issues.append("Луна в Раке описана как «считать/удерживать» (это Дева/Козерог)")
    if issues:
        add("WARN", f"E. Возможное противоречие достоинству планеты: {'; '.join(issues)} — проверить контекст.")
    else:
        add("PASS", "E. Противоречий достоинству планет (Марс/Луна в Раке) не обнаружено.")


# ── F. Анти-урок-джйотиш в клиентском тексте ────────────────────────
def check_jyotish_lesson(text):
    hits = []
    for pat in [r"управител\w*\s+накшатры", r"божеств\w*\s+накшатры",
                r"символ\w*\s+накшатры", r"накшатр\w*\s+управляет"]:
        if re.search(pat, text, flags=re.IGNORECASE):
            hits.append(pat)
    if hits:
        add("FAIL", f"F. Урок джйотиш в клиентском тексте (управитель/божество/символ накшатры): {hits} — убрать, дать денежный смысл накшатры.")
    else:
        add("PASS", "F. Нет «урока джйотиш» (управитель/божество/символ накшатры) в тексте.")


# ── G. Перегруз наставничеством ─────────────────────────────────────
def check_mentoring_overload(text):
    cnt = len(re.findall(r"наставнич", text, flags=re.IGNORECASE))
    if cnt > 3:
        add("WARN", f"G. «Наставничество» встречается {cnt} раз — не сводить большинство сфер к наставничеству (только где есть показатель).")
    else:
        add("PASS", f"G. Наставничество не перегружено ({cnt}).")


# ── H. Штампы-повторы, кочующие из разбора в разбор ────────────────
CLICHE_PHRASES = [
    r"когда\s+штормит",
    r"когда\s+другие\s+сдаются",
    r"к\s+кому\s+приходят\s+в\s+трудный\s+момент",
    r"к\s+вам\s+идут\s+с\s+самым\s+тяж[её]лым",
    r"вывод\w*\s+из\s+(?:кризиса|бури|шторма)",
    r"маяк\s+в\s+(?:кризисе|буре|шторме)",
    r"тот,?\s+к(?:ому|то)\s+выводит\s+из",
    r"входите?\s+туда,?\s+где\s+у\s+других\s+хаос",
    r"шторм\s+превращается\s+в\s+дорогу",
    r"к\s+вам\s+идут,?\s+когда\s+другие",
    r"вы\s+(?:сильнее|умеете)\s+(?:всего\s+)?там,?\s+где\s+надо\s+распутать",
]


def check_cliches(text):
    hits = []
    for pat in CLICHE_PHRASES:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            hits.append(m.group(0))
    if hits:
        uniq = sorted(set(h.lower() for h in hits))
        add("FAIL", f"H. Штампы-повторы ({len(hits)} шт.): {'; '.join(uniq[:5])} — переписать уникальным языком из накшатры/знака этого клиента.")
    else:
        add("PASS", "H. Штампов-повторов из других разборов не обнаружено.")


# ── I. Флагман-профессия не дублирует текст сферы 11 дословно ──────
def check_flagship_not_duplicate(text):
    block = get_spheres_block(text)
    if not block:
        return
    m11 = re.search(r"(?:^|\n)\s*11\.\s+\*\*(.+?)(?=\n\s*\*\*Профессия|$)", block, flags=re.DOTALL)
    flagship = re.search(r"\*\*Профессия,?\s+в которой[^*]+\*\*(.+?)(?=\n---|\n##|\Z)", block, flags=re.DOTALL)
    if not m11 or not flagship:
        return
    s11_text = m11.group(1).strip()[:300]
    fl_text = flagship.group(1).strip()[:300]
    fl_words = set(re.findall(r'\w{4,}', fl_text.lower()))
    s11_words = set(re.findall(r'\w{4,}', s11_text.lower()))
    if not fl_words:
        return
    overlap = len(fl_words & s11_words) / len(fl_words)
    if overlap > 0.6:
        add("FAIL", f"I. Флагман-профессия дублирует сферу 11 ({overlap:.0%} совпадение слов) — переписать уникальным синтезом.")
    else:
        add("PASS", "I. Флагман-профессия не дублирует сферу 11.")


# ── J. Выдуманные слова и неверные термины (причина 1) ──────────────
def check_no_fabricated(text):
    hits = []
    for pat in FABRICATED:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            hits.append(m.group(0))
    for m in re.finditer(COMPOUND_ASPECT, text, flags=re.IGNORECASE):
        hits.append(m.group(0))
    if hits:
        uniq = sorted(set(h.lower() for h in hits))
        add("FAIL", f"J. Выдуманные/неверные термины: {', '.join(uniq[:8])} — в тексте только реальные названия звёзд/цивилизаций и обычные слова.")
    else:
        add("PASS", "J. Нет выдуманных слов и неастрономических терминов.")


# ── K. Расчёты и формулы аспектов в клиентском тексте (причина 2) ───
def check_no_calculations(text):
    hits = []
    for pat in CALC_PATTERNS:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            hits.append(m.group(0).strip())
    if hits:
        uniq = sorted(set(hits))
        add("FAIL", f"K. Расчёты/формулы аспектов в тексте ({len(hits)} шт.): {', '.join(uniq[:6])} — аспект описывать словами, без чисел и выкладок.")
    else:
        add("PASS", "K. Нет расчётов/формул аспектов в клиентском тексте.")


# ── L. Служебные обороты и рассуждения агента (причина 2) ───────────
def check_no_meta(text):
    hits = []
    for pat in META_PATTERNS:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            hits.append(m.group(0).lower())
    if hits:
        uniq = sorted(set(hits))
        add("FAIL", f"L. Служебные обороты/рассуждения агента: {', '.join(uniq[:6])} — убрать, давать сразу готовый смысл.")
    else:
        add("PASS", "L. Нет служебных оборотов/рассуждений агента.")


# ── M. Одна услуга на раздел (причина: стэкинг услуг) ────────────────
def check_one_service_per_section(text):
    bad = []
    for h, b in split_sections(text):
        cnt = sum(b.count(a) for a in SERVICE_ANCHORS)
        if cnt > 1:
            bad.append(f"{h.lstrip('# ').strip()[:30]} ({cnt})")
    if bad:
        add("FAIL", f"M. В разделе больше 1 услуги: {'; '.join(bad)} — не более одной сервис-ссылки на раздел.")
    else:
        add("PASS", "M. Не более 1 услуги на раздел.")


# ── N. Разнообразие форматов: не копипастить «курсы/образование» ─────
def check_format_diversity(text):
    fam = re.findall(FORMAT_FAMILY, text, flags=re.IGNORECASE)
    block = get_spheres_block(text)
    spheres = re.split(r"(?m)^\s*\d+\.\s+\*\*", block)
    touched = sum(1 for s in spheres if re.search(FORMAT_FAMILY, s, flags=re.IGNORECASE))
    problems = []
    if len(fam) > FORMAT_GLOBAL_CAP:
        problems.append(f"«образование/курс» {len(fam)} раз (макс {FORMAT_GLOBAL_CAP})")
    if touched > FORMAT_SPHERES_CAP:
        problems.append(f"образование в {touched} сферах из 11 (макс {FORMAT_SPHERES_CAP}) — нужны другие профессии из карты")
    if problems:
        add("FAIL", f"N. Копипаст форматов: {'; '.join(problems)}.")
    else:
        add("PASS", "N. Форматы дохода разнообразны (без перекоса в образование).")


# ── O. Цивилизация на Асценденте раскрыта, не просто перечислена ─────
def check_asc_civilization(sections):
    _, b = find_section(sections, "АСЦЕНДЕНТ")
    if not b:
        return
    aspects = []
    for m in re.finditer(r"[☌☍△⚹□]\s*([^()\n]+?)\s*\(\s*\d", b):
        parts = [p.strip() for p in re.split(r"[/,]", m.group(1)) if len(p.strip()) >= 4]
        if parts:
            aspects.append(parts)
    if not aspects:
        add("PASS", "O. На Асценденте нет цивилизационных аспектов — проверка не применима.")
        return
    # тело без строк-перечислений аспектов (где стоят глифы)
    body_lines = [ln for ln in b.splitlines()
                  if not re.search(r"[☌☍△⚹□]|Цивилизац\w*\s+аспект", ln)]
    body = "\n".join(body_lines).lower()
    body_stems = set()
    for w in re.findall(r"[а-яё]+", body):
        if len(w) >= 4:
            body_stems.add(w[:5])
    unrevealed = []
    for parts in aspects:
        revealed = False
        for p in parts:
            if p.lower() in body:
                revealed = True
                break
            ps = _stems(p)
            if ps and ps <= body_stems:
                revealed = True
                break
        if not revealed:
            unrevealed.append("/".join(parts))
    if unrevealed:
        add("FAIL", f"O. Цивилизации на Асценденте только перечислены, не раскрыты: {', '.join(unrevealed[:5])} — описать сразу (ASC сильно влияет на личность).")
    else:
        add("PASS", "O. Цивилизации на Асценденте раскрыты в тексте.")


# ── P. Названия звёзд в аспектах сверены с картой клиента ────────────
def load_csv_allow(md_path):
    import os
    folder = os.path.dirname(md_path)
    allow = set(CIV_ALLOW)
    try:
        csvs = [f for f in os.listdir(folder) if f.lower().endswith(".csv")]
    except OSError:
        return allow
    for c in csvs:
        try:
            with open(os.path.join(folder, c), encoding="utf-8") as fh:
                for ln in fh:
                    if ln.startswith("#") or ";" not in ln:
                        continue
                    cols = ln.rstrip("\n").split(";")
                    if len(cols) >= 7:
                        for idx in (5, 6):  # Звезда, Созвездие
                            val = cols[idx].strip().lower()
                            if val and val != "звезда" and val != "созвездие":
                                allow.add(val)
        except OSError:
            continue
    return allow


def _stems(s):
    return {w[:5] for w in re.findall(r"[а-яё]+", s.lower()) if len(w) >= 4}


def check_star_names(text, md_path):
    allow = load_csv_allow(md_path)
    allow_stems = [st for st in (_stems(a) for a in allow) if st]
    suspects = []
    for m in re.finditer(r"[☌☍△⚹□]\s*([^()\n]+?)\s*\(\s*\d", text):
        raw = m.group(1).strip()
        parts = [p.strip().lower() for p in re.split(r"[/,]", raw) if len(p.strip()) >= 3]
        ok = False
        for p in parts:
            if any(p in a or a in p for a in allow):
                ok = True
                break
            ps = _stems(p)
            if ps and any(ps <= a for a in allow_stems):
                ok = True
                break
        if not ok and parts:
            suspects.append(raw)
    if suspects:
        uniq = sorted(set(suspects))
        add("FAIL", f"P. Названия звёзд вне карты клиента (возможна выдумка/ошибка): {', '.join(uniq[:6])} — сверить с CSV.")
    else:
        add("PASS", "P. Все названия звёзд в аспектах есть в карте клиента.")


# ── Q. Соединение 1-го дома сильнее аспекта — должно быть раскрыто ───
def _parse_csv_rows(md_path):
    import os
    folder = os.path.dirname(md_path)
    rows = []
    try:
        csvs = [f for f in os.listdir(folder) if f.lower().endswith(".csv")]
    except OSError:
        return rows
    for c in csvs:
        try:
            with open(os.path.join(folder, c), encoding="utf-8") as fh:
                for ln in fh:
                    if ln.startswith("#") or ";" not in ln:
                        continue
                    cols = [x.strip() for x in ln.rstrip("\n").split(";")]
                    if len(cols) >= 7 and cols[0] != "Планета":
                        rows.append(cols)  # Планета;Градус;Накшатра;Дома;Аспект;Звезда;Созвездие;Орбис
        except OSError:
            continue
    return rows


def check_asc_conjunction(sections, md_path):
    rows = _parse_csv_rows(md_path)
    if not rows:
        return
    # Группируем соединения 1-го дома по якорю (Асцендент / планета в 1-м доме).
    # Описывается ГЛАВНОЕ (самое тугое по орбу) соединение каждого якоря.
    anchors = {}
    for cols in rows:
        planet, house, aspect, star, orb = cols[0], cols[3], cols[4], cols[5], cols[7]
        if aspect.lower().startswith("соединени") and (planet == "Асцендент" or house == "1"):
            try:
                o = float(orb)
            except ValueError:
                o = 99.0
            anchors.setdefault(planet, []).append((o, star))
    required = set()
    for _, lst in anchors.items():
        lst.sort()
        required.add(lst[0][1])
    if not required:
        add("PASS", "Q. На Асценденте/в 1-м доме нет соединений со звёздами — проверка не применима.")
        return
    _, b = find_section(sections, "АСЦЕНДЕНТ")
    if not b:
        add("FAIL", "Q. Раздел АСЦЕНДЕНТ не найден — соединения 1-го дома не проверить.")
        return
    body_low = b.lower()
    body_stems = set()
    for w in re.findall(r"[а-яё]+", body_low):
        if len(w) >= 4:
            body_stems.add(w[:5])
    missing = []
    for star in required:
        if star.lower() in body_low:
            continue
        st = _stems(star)
        if st and st <= body_stems:
            continue
        missing.append(star)
    if missing:
        add("FAIL", f"Q. В 1-м доме есть СОЕДИНЕНИЕ (сильнее аспекта) с {', '.join(sorted(missing))}, но в разделе АСЦЕНДЕНТ оно не раскрыто как цивилизация — соединение описывается ВСЕГДА, приоритетнее тринов/секстилей.")
    elif "☌" in b or re.search(r"соединени", b, flags=re.IGNORECASE):
        add("PASS", "Q. Соединения 1-го дома раскрыты в разделе АСЦЕНДЕНТ.")
    else:
        add("FAIL", "Q. Соединения 1-го дома есть в карте, но в разделе АСЦЕНДЕНТ не обозначены как соединения (☌) — отделить от аспектов.")


# ── R. Книга — только в разделе, где есть цивилизации ───────────────
def check_book_near_civ(text):
    if "/book/" not in text:
        return
    for h, b in split_sections(text):
        if "/book/" not in b:
            continue
        has_civ = (
            "☌" in b
            or "СПОСОБ МАТЕРИАЛИЗАЦИИ" in b
            or re.search(r"кто\s+эти\s+существа", b, flags=re.IGNORECASE)
            or re.search(r"цивилизаци", b, flags=re.IGNORECASE)
        )
        if has_civ:
            add("PASS", "R. Книга стоит в разделе с цивилизациями.")
        else:
            add("FAIL", f"R. Книга в разделе «{h.lstrip('# ').strip()[:30]}», где нет цивилизаций — перенести туда, где есть соединение/цивилизация.")
        return


# ── S. Орб в тексте обязан совпадать с картой (CSV) ─────────────────
import difflib


def _name_words(s):
    return re.findall(r"[а-яё]+", s.lower())


def _name_matches(name, star):
    a = _name_words(name)
    b = _name_words(star)
    if not a or len(a) != len(b):
        return False
    for wa, wb in zip(a, b):
        if difflib.SequenceMatcher(None, wa, wb).ratio() < 0.8:
            return False
    return True


def _csv_star_orbs(md_path):
    m = {}
    for cols in _parse_csv_rows(md_path):
        star = cols[5].strip().lower()
        try:
            o = round(float(cols[7]), 2)
        except (ValueError, IndexError):
            continue
        if star and star not in ("звезда",):
            m.setdefault(star, set()).add(o)
    return m


def check_orb_consistency(text, md_path):
    star_orbs = _csv_star_orbs(md_path)
    if not star_orbs:
        return
    bad = []
    for m in re.finditer(r"([А-ЯЁ][А-Яа-яё\- ]{2,30}?)\s*\(([^)]*?)(\d+\.\d+)\s*°", text):
        name = m.group(1).strip()
        try:
            orb = round(float(m.group(3)), 2)
        except ValueError:
            continue
        target = None
        # пословное сравнение с РАВНЫМ числом слов и схожестью ≥0.8.
        # Так «Альнилам»≠«Альният», «Галактический Центр»≠
        # «Сверх-Галактический Центр» (разное число слов), но падежи
        # ловятся («Галактическим Центром» = «Галактический Центр»).
        for star in star_orbs:
            if _name_matches(name, star):
                target = star
                break
        if target is None:
            continue  # не звезда из карты — орб не сверяем (имя ловит P)
        if not any(abs(orb - o) <= 0.05 for o in star_orbs[target]):
            bad.append(f"{name} в тексте {orb}° ≠ карта {sorted(star_orbs[target])}")
    if bad:
        add("FAIL", f"S. Орб в тексте не совпадает с картой ({len(bad)} шт.): {'; '.join(bad[:6])} — взять точное значение орба из CSV.")
    else:
        add("PASS", "S. Орбы звёзд в тексте совпадают с картой клиента.")


# ── T. Своё соединение раздела раскрыто как цивилизация ──────────────
def _header_own_conjunctions(body):
    """☌-имена из метаданных раздела (первая строка с **Дом/Знак**),
    кроме сегментов про управителя/диспозитора (это чужие планеты)."""
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        return []
    head = lines[0]
    if not re.match(r"\s*\*\*(Дом|Знак)", head):
        return []
    if "☌" not in head:
        return []
    names = []
    for seg in head.split("|"):
        if "☌" not in seg:
            continue
        if re.search(r"управител|диспозитор", seg, flags=re.IGNORECASE):
            continue
        for m in re.finditer(r"☌\s*([^()|;,]+?)\s*(?:\(|$|;|,)", seg):
            nm = re.split(r"/", m.group(1).strip())[0].strip()
            if len(nm) >= 3:
                names.append(nm)
    return names


def check_section_conj_revealed(sections):
    problems = []
    any_checked = False
    for h, b in sections:
        names = _header_own_conjunctions(b)
        if not names:
            continue
        any_checked = True
        revealed = ("СПОСОБ МАТЕРИАЛИЗАЦИИ" in b) or (
            re.search(r"кто\s+эти\s+существа", b, flags=re.IGNORECASE) is not None
        )
        if not revealed:
            problems.append(f"{h.lstrip('# ').strip()[:24]} → {', '.join(names[:3])}")
    if problems:
        add("FAIL", f"T. Своё соединение раздела не раскрыто как цивилизация (нет «Кто эти существа»/«СПОСОБ МАТЕРИАЛИЗАЦИИ»): {'; '.join(problems[:5])} — описать существ и способ материализации в этом же разделе.")
    elif any_checked:
        add("PASS", "T. Все собственные соединения разделов раскрыты как цивилизации.")
    else:
        add("PASS", "T. В шапках разделов нет своих соединений — проверка не применима.")


# ── V. Плотность конкретных профессий (не «только образно») ──────────
PROFESSION_STEMS = [
    "психолог", "психотерап", "терапевт", "коуч", "консультант", "консалт",
    "эксперт", "аналит", "директор", "продюс", "менедж", "куратор",
    "организатор", "руковод", "специалист", "врач", "управляющ", "аудит",
    "преподават", "тренер", "ментор", "маркетолог", "дизайнер", "архитектор",
    "стратег", "медиатор", "реабилит", "диагност", "исследоват", "методолог",
    "хирург", "скаут", "редактор", "наставник", "целител", "фасилитат",
    "супервиз", "расстанов",
]


def check_profession_density(text):
    found = {s for s in PROFESSION_STEMS if re.search(s, text, flags=re.IGNORECASE)}
    spheres = get_spheres_block(text)
    sph_found = (
        {s for s in PROFESSION_STEMS if re.search(s, spheres, flags=re.IGNORECASE)}
        if spheres else set()
    )
    if len(found) < 6:
        add("WARN", f"V. Мало конкретных профессий ({len(found)}) — разбор рискует быть «только образным». Добавить реальные названия профессий в блоки СПОСОБ МАТЕРИАЛИЗАЦИИ и в 11 сфер.")
    elif spheres and len(sph_found) < 4:
        add("WARN", f"V. Профессии есть в целом ({len(found)}), но в «11 сферах» их мало ({len(sph_found)}) — конкретика не должна быть только в эзотерических блоках; добавить названия профессий в материальные и масштабные сферы.")
    else:
        add("PASS", f"V. Конкретные профессии присутствуют ({len(found)} всего, {len(sph_found)} в 11 сферах).")


# ── W. Взаимосвязи планет-стеллиумов синтезированы, не по одиночке ────
def _csv_stelliums(md_path):
    """Дома с 2+ планетами (стеллиум) из CSV: {дом: {планеты}}."""
    houses = {}
    for cols in _parse_csv_rows(md_path):
        planet, house = cols[0].strip(), cols[3].strip()
        if planet in PLANET_STEMS and house.isdigit():
            houses.setdefault(house, set()).add(planet)
    return {h: p for h, p in houses.items() if len(p) >= 2}


def check_interconnections(text, md_path):
    stelliums = _csv_stelliums(md_path)
    if not stelliums:
        add("PASS", "W. Стеллиумов (2+ планеты в одном доме) в карте нет — синтез связей не требуется.")
        return
    paras = re.split(r"\n\s*\n", text)
    problems = []
    for house, planets in stelliums.items():
        ok = False
        for para in paras:
            hits = sum(
                1 for pl in planets
                if re.search(PLANET_STEMS[pl], para, flags=re.IGNORECASE)
            )
            if hits >= 2 and re.search(CONNECT_WORDS, para, flags=re.IGNORECASE):
                ok = True
                break
        if not ok:
            problems.append(f"{house}-й дом: {', '.join(sorted(planets))}")
    if problems:
        add("FAIL", f"W. Планеты-стеллиумы описаны по одиночке без синтеза связи ({'; '.join(problems[:5])}) — добавить абзац: как эти планеты влияют друг на друга и работают вместе на деньги.")
    else:
        add("PASS", "W. Все стеллиумы раскрыты как взаимосвязь планет, а не по одиночке.")


def main():
    if len(sys.argv) < 2:
        print("Использование: python .cursor/skills/2-money-analysis/money_validate.py <путь к файлу>")
        sys.exit(2)
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        text = f.read()

    # текст без строк-цитат (дисклеймер) для проверки местоимений
    text_no_quotes = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith(">")
    )

    sections = split_sections(text)

    check_third_person(text_no_quotes)
    check_jargon(text)
    check_latin_in_cyrillic(text)
    check_order(text)
    check_spheres(text)
    check_practices(text)
    check_links(text)
    check_civilizations(text)
    check_abstractions(text)
    # Жёсткие проверки по карте-нюансам (A–G), добавлено 03.06.2026
    check_dispositors(sections)          # A
    check_flagship(text)                 # B
    check_sphere_layers(text)            # C
    check_attractor_filter(sections)     # D
    check_dignity(text)                  # E (WARN)
    check_jyotish_lesson(text)           # F
    check_mentoring_overload(text)       # G (WARN)
    check_cliches(text)                  # H
    check_flagship_not_duplicate(text)   # I
    # Корневые принципы (Дарья, 07.06.2026): выдумка, расчёты, копипаст
    check_no_fabricated(text)            # J
    check_no_calculations(text)          # K
    check_no_meta(text)                  # L
    check_one_service_per_section(text)  # M
    check_format_diversity(text)         # N
    check_asc_civilization(sections)     # O
    check_star_names(text, path)         # P
    check_asc_conjunction(sections, path)  # Q
    check_book_near_civ(text)            # R
    # Корневые принципы (Дарья, 07.06.2026, разбор Марты): орб=карта,
    # своё соединение раскрыто, услуга по смыслу, конкретные профессии
    check_orb_consistency(text, path)        # S
    check_section_conj_revealed(sections)    # T
    check_energodush_meaning(text)           # U
    check_profession_density(text)           # V (WARN)
    check_interconnections(text, path)       # W

    print("=" * 60)
    print(f"ВАЛИДАЦИЯ: {path}")
    print("=" * 60)
    fails = 0
    for level, msg in results:
        mark = {"PASS": "[ OK ]", "FAIL": "[FAIL]", "WARN": "[WARN]"}[level]
        print(f"{mark} {msg}")
        if level == "FAIL":
            fails += 1
    print("=" * 60)
    if fails:
        print(f"РЕЗУЛЬТАТ: {fails} FAIL — показывать Дарье ЗАПРЕЩЕНО, исправить и перезапустить.")
        sys.exit(1)
    print("РЕЗУЛЬТАТ: все проверки пройдены. Можно показывать Дарье.")
    sys.exit(0)


if __name__ == "__main__":
    main()
