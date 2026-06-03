#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
money_validate.py — жёсткий гейт-валидатор разбора ДНК денег.

Запуск ОБЯЗАТЕЛЕН перед показом разбора Дарье.
Пока есть хоть один [FAIL] — показывать файл ЗАПРЕЩЕНО.

Использование (из корня Producty):
    python .cursor/skills/2-money-analysis/money_validate.py "<путь к *_деньги.md>"
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
    "5 ГЛАВНЫХ СИЛ И 5 ГЛАВНЫХ ТЕНЕЙ",
    "ПРАКТИКИ",
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

    # практики ДО сопровождения, сопровождение предпоследнее
    if "ПРАКТИКИ" in found_order and "СОПРОВОЖДЕНИЕ" in found_order:
        if found_order.index("ПРАКТИКИ") < found_order.index("СОПРОВОЖДЕНИЕ"):
            add("PASS", "ПРАКТИКИ идут до СОПРОВОЖДЕНИЯ (Сопровождение последнее).")
        else:
            add("FAIL", "ПРАКТИКИ стоят после СОПРОВОЖДЕНИЯ — переставить: Сопровождение должно быть последним блоком.")


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


def check_energodush_in_saturn(text):
    # Энергодуш должен стоять в разделе САТУРН
    sat = re.search(r"##\s+\d*\.?\s*САТУРН.*?(?=\n##\s)", text, flags=re.DOTALL)
    if sat and "cleansing-202" in sat.group(0):
        add("PASS", "Энергодуш — в разделе САТУРН.")
    elif "cleansing-202" in text:
        add("FAIL", "Энергодуш стоит НЕ в разделе САТУРН — перенести туда (раз указан Сатурн).")
    else:
        add("FAIL", "Ссылка на Энергодуш не найдена.")


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

    check_third_person(text_no_quotes)
    check_jargon(text)
    check_latin_in_cyrillic(text)
    check_order(text)
    check_spheres(text)
    check_practices(text)
    check_links(text)
    check_energodush_in_saturn(text)
    check_civilizations(text)
    check_abstractions(text)

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
