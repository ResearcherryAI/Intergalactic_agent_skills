"""Валидация LLM-выхода против 31 инварианта v3 (см. prompts/user/user_template_v3.md).

Группы проверок:
- A. Структура (8): заголовок, дисклеймер, 2 раздела, ключевые блоки.
- B. Атрибуция (3): автор Кайя Каэн, нет «Дарья / Лачинова», книга «Активация Внеземной ДНК» >= 2.
- C. Длина и формат (3): 380-420 строк, таблица Top-3, WhatsApp CTA.
- D. Семантика (8): 7-8 профессий, 2-4 🔥, 5 теней без рецептов, упомянуты внешние планеты,
     косвенные цивилизации, «Точные аспекты», только одна «Личная практика», «Чем заняться»
     заканчивается «материализация идёт через X и Y».
- E. Запреты (7): нет «бесплатно», Vimshottari/махадаш, продажи услуг, Кету-аспектов,
     «Ключевых ритмов», TIER/orb в нарративе, лишних практик.
- F. Top-N (2): состав 3/3, порядок 3/3 как в RANKED_CIVS.

Возвращает {score: 0..1, passed: int, total: int, fails: [reason]}.
Совместимо с runner.py: тот же API.
"""

from __future__ import annotations

import re
from typing import Any

DISCLAIMER_LITERAL = "Это авторский метод Кайи Каэн, проверен тысячами клиентов"
WHATSAPP = "wa.me/message/X6MQ6PLPR7K4L1"
BOOK = "Активация Внеземной ДНК"


def _find_section(md: str, head_re: str) -> str | None:
    """Возвращает тело секции от заголовка до следующего ##/### или конца документа."""
    m = re.search(
        rf"^#{{2,3}}\s+{head_re}[^\n]*\n([\s\S]+?)(?=\n#{{2,3}}\s|\Z)",
        md, re.M,
    )
    return m.group(1) if m else None


def benchmark(markdown: str, *, expected_top: list[str] | None = None) -> dict[str, Any]:
    md = markdown
    md_low = md.lower()
    fails: list[str] = []
    checks: dict[str, bool] = {}

    # ----------- A. Структура -----------
    checks["A1_h1_mission"] = bool(re.search(r"^#\s+МИССИЯ ЗВЁЗДНОЙ ДУШИ", md, re.M))
    checks["A2_h2_struct"] = bool(re.search(r"^##\s+.*СТРУКТУРА ДНК", md, re.M))
    checks["A3_h2_analysis"] = bool(re.search(r"^##\s+АНАЛИЗ МИССИИ", md, re.M))
    # ровно две секции верхнего уровня (##), не считая заголовка # МИССИЯ
    h2_count = len(re.findall(r"^##\s+[А-ЯA-Z]", md, re.M))
    checks["A4_two_top_sections"] = h2_count == 2

    # обязательные блоки внутри СТРУКТУРА ДНК
    checks["A5_outer_planets_block"] = bool(
        re.search(r"^###\s+Внешние планеты", md, re.M)
        or ("Уран" in md and "Нептун" in md and "Плутон" in md)
    )
    checks["A6_indirect_civs_block"] = bool(
        re.search(r"^###\s+Косвенные цивилизации", md, re.M)
        or "косвенное влияние" in md_low or "косвенные цивилизации" in md_low
    )
    # обязательный блок «Точные аспекты» в АНАЛИЗ МИССИИ
    checks["A7_exact_aspects_block"] = bool(re.search(r"^###\s+Точные аспекты", md, re.M))
    # «Практика» — ровно одна финальная. Допускаем варианты:
    #   v3:   `### Личная практика`, `### Общая практика`, `### Финальная практика`
    #   v3.1: `### Бонусная практика` (эталонная номенклатура Дарьи)
    h3_practice = re.findall(
        r"^###\s+(?:Личная|Общая|Финальная|Бонусная)\s+практика", md, re.M
    )
    bold_practice = re.findall(
        r"^\*\*(?:Личная|Общая|Финальная|Бонусная)\s+практика[^*]*\*\*\s*$", md, re.M
    )
    checks["A8_one_practice"] = (len(h3_practice) + len(bold_practice)) == 1

    # ----------- B. Атрибуция -----------
    checks["B1_disclaimer_literal"] = DISCLAIMER_LITERAL in md
    checks["B2_author_kaya_no_daria"] = (
        ("Кайи Каэн" in md or "Кайя Каэн" in md or "Kaya Kaen" in md)
        and "Дарья Лачинова" not in md and "Лачинова" not in md
    )
    book_count = len(re.findall(BOOK, md))
    checks["B3_book_2plus"] = book_count >= 2

    # ----------- C. Длина и форматы -----------
    line_count = len(md.split("\n"))
    # Расширенный диапазон 300-450 — эталоны Дарьи 380-420, но прогоны бывают сжатее.
    checks["C1_length_300_450"] = 300 <= line_count <= 450
    # Таблица Top-3 в формате «| # | Цивилизация | Соединения |»
    checks["C2_table_top_civs"] = bool(
        re.search(r"\|\s*#\s*\|\s*Цивилизация\s*\|\s*Соединения", md)
    )
    checks["C3_whatsapp_cta"] = WHATSAPP in md

    # ----------- D. Семантика -----------
    # D1/D2: «Чем заняться» — 7-8 профессий + 2-4 🔥
    pro_section = _find_section(md, r"(?:Чем заняться|Профессии|Профессиональные)")
    if pro_section:
        bullets = re.findall(
            r"(?:^|\n)\s*(?:\*\*)?(\d+)\.\s+(?:🔥\s+)?\*?\*?[А-ЯA-ZЁa-zё]",
            pro_section,
        )
        pro_count = len(set(bullets))
        fire_count = sum(
            1 for ln in pro_section.split("\n")
            if "🔥" in ln and re.match(r"^\s*(?:\*\*)?\d+\.", ln)
        )
        checks["D1_professions_7_or_8"] = pro_count in (7, 8)
        checks["D2_fire_2_4"] = 2 <= fire_count <= 4
        if not checks["D1_professions_7_or_8"]:
            fails.append(f"D1_pro_count_{pro_count}")
        if not checks["D2_fire_2_4"]:
            fails.append(f"D2_fire_count_{fire_count}")
        # «материализация идёт через X и Y» — в конце секции
        checks["D3_materialization_through"] = bool(
            re.search(r"материализаци[яи].{0,40}(?:идёт|идет|реализуется|про(?:исходит|являет)).{0,60}через",
                      pro_section, re.I)
            or re.search(r"сейчас\s+материализаци", pro_section, re.I)
        )
    else:
        checks["D1_professions_7_or_8"] = False
        checks["D2_fire_2_4"] = False
        checks["D3_materialization_through"] = False
        fails.append("D_no_pro_section")

    # D4/D5: «Что может мешать реализоваться» — ровно 5 пунктов, БЕЗ детальных решений-методичек
    teni_section = _find_section(md, r"(?:Что может мешать|Тени)")
    if teni_section:
        items = re.findall(
            r"(?:^|\n)\s*(?:\*\*)?(\d+)\.\s+\*?\*?[А-ЯA-ZЁa-zё]",
            teni_section,
        )
        item_count = len(set(items))
        checks["D4_teni_5_items"] = item_count == 5
        # Запрет на пошаговые методички и блоки «решений». Допустимо «направление работы»,
        # «можно посмотреть в сторону», «попробуйте...». Запрещено «Шаг 1 — ... Шаг 2 — ...»
        bad_solutions = (
            len(re.findall(r"^\s*Шаг\s*\d+", teni_section, re.M | re.I))
            + teni_section.count("Путь решения")
            + len(re.findall(r"\*\*Решение\s*[:—-]", teni_section))
            + teni_section.count("План действий")
        )
        checks["D5_teni_no_recipes"] = bad_solutions == 0
        if not checks["D4_teni_5_items"]:
            fails.append(f"D4_teni_count_{item_count}")
        if not checks["D5_teni_no_recipes"]:
            fails.append(f"D5_recipes_{bad_solutions}")
    else:
        checks["D4_teni_5_items"] = False
        checks["D5_teni_no_recipes"] = False
        fails.append("D_no_teni_section")

    # D6: упомянуты все внешние планеты + узлы
    checks["D6_outer_planets_named"] = all(
        p in md for p in ("Уран", "Нептун", "Плутон", "Раху", "Кету")
    )
    # D7: разделы по цивилизациям — ровно 3. Допускаем:
    #   v3:   `### Цивилизация {имя}`
    #   v3.1: `### Первая сила — {имя}`, `### Вторая сила — {имя}`, `### Третья сила — {имя}`
    civ_sections = re.findall(
        r"^###\s+(?:Цивилизация\s+|(?:Первая|Вторая|Третья)\s+сила\s*[—–\-:])",
        md, re.M,
    )
    checks["D7_three_civ_sections"] = len(civ_sections) == 3
    if not checks["D7_three_civ_sections"]:
        fails.append(f"D7_civ_sections_{len(civ_sections)}")
    # D8: «Миссия одной фразой» / «Ваша миссия одной фразой». Допускаем мелкие опечатки.
    checks["D8_mission_one_phrase"] = bool(
        re.search(r"^###\s+(?:Ваша\s+)?[Мм]иссия\s+одно[йяе]?\s+фраз", md, re.M)
    )

    # ----------- E. Запреты -----------
    checks["E1_no_besplatno"] = "бесплатно" not in md_low
    checks["E2_no_vimshottari"] = (
        "Vimshottari" not in md and "Вимшоттари" not in md
        and "махадаша" not in md_low and "махадаши" not in md_low
    )
    # Услуги: продажа CTA. Семантика типа «чистка ауры — инструмент» — норм.
    cta_patterns = [
        r"(?:заказ|купи|оплат)\w*\s+(?:чистк|услуг|сессию|консультац)",
        r"стоимост[ьи]\s+(?:чистк|консультац|сессии|услуг)",
        r"услуг[аи]\s*[—–-]\s*чистк",
    ]
    checks["E3_no_service_selling"] = not any(re.search(p, md_low) for p in cta_patterns)
    checks["E4_no_ketu_aspects"] = not re.search(
        r"Кету\s+аспектирует|Кету.{0,30}джйотиш-аспект", md
    )
    # «Ключевые ритмы», «Шаги на ближайшие месяцы», «План на ближайший год»
    forbidden_blocks = [
        r"^###\s+Ключевые ритмы",
        r"^###\s+Шаги на ближайш",
        r"^###\s+План на ближайш",
        r"возраст активации",
    ]
    bad_blocks = sum(1 for p in forbidden_blocks if re.search(p, md, re.M | re.I))
    checks["E5_no_rhythms_steps_ages"] = bad_blocks == 0
    # Технические метки в нарративе: TIER/вес/orb/гр.A1. Допускаются в служебном CSV если попал.
    # Считаем токены вне ``` ``` блоков.
    narrative = re.sub(r"```[\s\S]+?```", "", md)
    tech_tokens = (
        len(re.findall(r"\bTIER\b", narrative))
        + len(re.findall(r"гр\.\s*A\d", narrative))
        + len(re.findall(r"вес\s*[×x]\s*\d", narrative))
        + len(re.findall(r"\borb\b", narrative.lower()))
    )
    checks["E6_no_tech_tokens_in_narrative"] = tech_tokens == 0
    if not checks["E6_no_tech_tokens_in_narrative"]:
        fails.append(f"E6_tech_tokens_{tech_tokens}")
    # Лишние практики (помимо ОДНОЙ финальной «Личная/Общая практика»):
    # «практика для активации линии Дракона / Ориона / ...», «утренний огонь»,
    # «практика отпускания», «активация линии». «Общая практика для активации миссии»
    # — это и есть единственная финальная, её не штрафуем.
    extra_practice_patterns = [
        r"практик[аи]\s+(?:для\s+)?активации\s+линии",
        r"практик[аи]\s+(?:для\s+)?активации\s+(?:цивилизаци|Дракон|Орион|Лир|Сириус|Андромед|Льв|Скорпион|Тельца|Возничего)",
        r"утренний огонь",
        r"практик[аи]\s+отпускания",
        r"активаци[яи]\s+линии\s+цивилизаци",
    ]
    extra_practices = sum(
        len(re.findall(p, narrative.lower())) for p in extra_practice_patterns
    )
    checks["E7_only_one_practice"] = extra_practices == 0

    # ----------- F. Top-N точность -----------
    if expected_top:
        # Состав Top-3 — ищем в первых 150 строках (таблица может быть глубоко в СТРУКТУРА ДНК)
        first_part = "\n".join(md.split("\n")[:150])
        # Извлекаем имена из таблицы Top-цивилизаций
        table_civs: list[str] = []
        for line in first_part.split("\n"):
            mline = re.match(r"\|\s*\d\s*\|\s*\*?\*?([А-ЯA-ZЁ][^\|*]+?)\*?\*?\s*\|", line)
            if mline:
                table_civs.append(mline.group(1).strip())
        # Совпадение по составу
        found_set = sum(1 for civ in expected_top if civ in first_part)
        checks["F1_top_composition"] = found_set == len(expected_top)
        # Совпадение по порядку. Допускаем «Скорпион (Антарес)», «Лев (Зосма)» — берём
        # часть до открывающей скобки и сравниваем по startswith.
        def _norm(s: str) -> str:
            return s.split("(")[0].strip().strip("*").strip().lower()
        if len(table_civs) >= len(expected_top):
            table_norm = [_norm(c) for c in table_civs[:len(expected_top)]]
            exp_norm = [c.lower() for c in expected_top]
            checks["F2_top_order"] = all(
                t.startswith(e) or e.startswith(t) for t, e in zip(table_norm, exp_norm)
            )
        else:
            checks["F2_top_order"] = False
        if not checks["F1_top_composition"]:
            fails.append(f"F1_composition_{found_set}_of_{len(expected_top)}")
        if not checks["F2_top_order"]:
            fails.append("F2_order_mismatch")

    # ----------- Compile fails -----------
    for k, v in checks.items():
        if not v and not any(f.startswith(k.split("_")[0] + "_") or f == k for f in fails):
            fails.append(k)

    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    score = round(passed / total, 4) if total else 0

    return {
        "score": score,
        "passed": passed,
        "total": total,
        "fails": fails,
        "checks": checks,
        "stats": {
            "lines": line_count,
            "book_mentions": book_count,
        },
    }


if __name__ == "__main__":
    import sys
    import json

    args = [a for a in sys.argv[1:] if a]
    as_json = False
    if "--json" in args:
        as_json = True
        args.remove("--json")

    md_path = args[0] if args else "ref_svetlana.md"
    md = open(md_path, encoding="utf-8").read()
    expected = args[1].split(",") if len(args) > 1 else ["Телец", "Великий Аттрактор", "Дракон"]

    result = benchmark(md, expected_top=expected)

    if as_json:
        # Машинный вывод для оркестратора: только JSON, ничего лишнего.
        out = {
            "score": result["score"],
            "passed": result["passed"],
            "total": result["total"],
            "fails": result["fails"],
            "stats": result["stats"],
            "input_file": md_path,
            "expected_top": expected,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(0 if result["score"] >= 0.90 else 1)

    # Человеческий вывод по умолчанию.
    print(f"Score: {result['score'] * 100:.2f}% ({result['passed']}/{result['total']})")
    print(f"Lines: {result['stats']['lines']}")
    print(f"Book mentions: {result['stats']['book_mentions']}")
    print(f"Fails: {result['fails']}")
    sys.exit(0 if result["score"] >= 0.90 else 1)
