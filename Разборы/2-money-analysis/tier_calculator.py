"""
TIER-расчёт цивилизаций (v3.2, эксперимент R0-R7 от 19.05.2026 на 10 клиентах).

Изменения v3.3 vs v3.2 — правило R8:
  1. Если цивилизация имеет точное личное соединение (orb < 1°) и тот же
     цивилизационный канал подтверждён узлом в ближнем шлейфе 2°..3°, она
     поднимается в группу `A_personal_node_trail` (rank 4.5).
  2. Это ставит такую линию выше одиночной узловой GC-точки `A_gc_wide`,
     но ниже точного outer-соединения и nodes-multi.
  3. Мотивация: кейс Ларисы 26.05.1965 — Орион (Венера ☌ Ригель 0.36° +
     Раху ☌ Ригель 2.04° как шлейф) должен быть Top-3, а одиночный
     Кету ☌ Великий Аттрактор 0.76° — дополнительным влиянием.

Изменения v3.2 vs v3.1 — правило R7 (системное, не эвристика):
  Цивилизация принудительно поднимается в Top если выполнено хотя бы одно:
  1. Суммарный вес цивилизации ≥ 5.0 — много контактов или один очень тугой
     → группа `A1` (rank 0).
  2. ≥ 2 уникальных звезды этой цивилизации задеты в орбе < 1° любыми
     планетами (включая outer), при условии что хотя бы одна планета
     НЕ узловая (не только Раху/Кету)
     → группа `A1_multi_personal_mid` (rank 2.5).
  Эффект на 10 клиентах: in-set 28→30 (100%), exact 26→28 (93.3%),
  никого не сломал. Подробности эксперимента — `TIER_CALCULATOR_SPEC.md`.

Изменения v3.1 vs v3.0:
- TOP_N = 3 жёстко (Дарья: «должно быть максимум 3»).
- Outer-планеты разделены на «узкие» (orb < 1°) и «широкие» (1° ≤ orb < 5°).
- Nodes-only multi-star цивилизация может попадать в Top.
- Добавлены косвенные цивилизации (orb 2-5° personal/node, 5-10° outer).
- Добавлен compute_ascendant_data: знак, диспозитор, дом-1 — детерминированно.

Финальные правила:

1. Аспект — только "Соединение" учитывается для веса цивилизаций.

2. Орб-пороги для конъюнкции:
   - Outer planet (Уран/Нептун/Плутон):
     - orb < 1.0° → TIER 0 узкий, вес ×3, основной
     - 1.0° ≤ orb < 5.0° → TIER 0 широкий, вес ×3, основной но второстепенный
     - 5.0° ≤ orb < 10.0° → косвенное влияние, не в Top
   - Personal/node:
     - orb < 0.2° → TIER 1, вес ×3
     - 0.2° ≤ orb < 1.0° → TIER 2, вес ×2
     - 1.0° ≤ orb < 2.0° → TIER 3, вес ×1.5
     - 2.0° ≤ orb < 5.0° → косвенное влияние, не в Top

3. GC-boost: соединения с GC/Сверх-ГЦ/Великим Аттрактором/Аттрактором Шепли
   повышают тир на 1 (для не-outer, включая узлы):
   - TIER 3+GC → TIER 2
   - TIER 2+GC → TIER 1

4. Имя цивилизации:
   - Если звезда — GC-точка (4 точки) → имя = звезда (отдельная цивилизация).
   - Иначе → нормализованное созвездие через SKY_GROUPING.
   - Асцендент НЕ учитывается как планета (точка карты).

5. Группы приоритета:
   - A1: multi-star non-node — ≥2 уникальные звезды, хотя бы одна планета не-нода.
   - A2: outer planet TIER 0 узкий (orb < 1°) с одной звездой.
   - A3: multi-star nodes-only — ≥2 уникальные звезды только через Раху/Кету.
   - B:  TIER 1 personal (orb < 0.2°) с одной звездой.
   - C:  outer planet TIER 0 широкий (1° ≤ orb < 5°) с одной звездой.
   - D:  TIER 2/3 personal/node single — слабые одиночные.

6. Сортировка eligible: группа (A1→D), вес desc, min_orb asc.

7. Top-N = 3 ЖЁСТКО.

8. Косвенные цивилизации (indirect) — orb на границе допустимого, фиксируются
   отдельно для упоминания LLM как «косвенное влияние».
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SKY_GROUPING: dict[str, str] = {
    "Плеяды": "Телец",
    "Телец (Гиады)": "Телец",
    "Туманность Ориона (M42)": "Орион",
    "Кольцо Лиры (M57)": "Лира",
    "М. Пёс": "Малый Пёс",
    "Б. Пёс": "Большой Пёс (Сириус)",
    "Юж. Рыба": "Южная Рыба",
    "М. Медведица": "Полярная (М. Медведица)",
}

NODES: set[str] = {"Раху", "Кету"}
OUTER_PLANETS: set[str] = {"Уран", "Нептун", "Плутон"}
EXCLUDED_POINTS: set[str] = {"Асцендент"}

GC_POINTS: set[str] = {
    "Галактический Центр",
    "Сверх-Галактический Центр",
    "Великий Аттрактор",
    "Аттрактор Шепли",
}

# Орб-пороги (v3.1)
ORB_OUTER_TIGHT_MAX = 1.0   # < 1° для outer → TIER 0 узкий
ORB_OUTER_WIDE_MAX = 5.0    # 1°..5° для outer → TIER 0 широкий
ORB_OUTER_INDIRECT_MAX = 10.0  # 5°..10° для outer → косвенное

ORB_REGULAR_MAX = 2.0       # < 2° для personal/node → TIER 1/2/3
ORB_REGULAR_INDIRECT_MAX = 5.0  # 2°..5° для personal/node → косвенное
ORB_NODE_TRAIL_MAX = 3.0    # 2°..3° узловой шлейф усиливает точную личную линию

TOP_N = 3  # жёстко (v3.1)

# Знаки зодиака (sidereal) и их управители для Лагнеши
ZODIAC_SIGNS: list[tuple[str, str]] = [
    ("Овен",     "Марс"),
    ("Телец",    "Венера"),
    ("Близнецы", "Меркурий"),
    ("Рак",      "Луна"),
    ("Лев",      "Солнце"),
    ("Дева",     "Меркурий"),
    ("Весы",     "Венера"),
    ("Скорпион", "Марс"),
    ("Стрелец",  "Юпитер"),
    ("Козерог",  "Сатурн"),
    ("Водолей",  "Сатурн"),
    ("Рыбы",     "Юпитер"),
]


# ---------------------------------------------------------------------------
# Парсинг
# ---------------------------------------------------------------------------

def _parse_orb(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).strip().replace(",", "."))


def _parse_degree(s: str) -> float:
    """Парсит «301°43'20"» → 301.7222 (десятичные градусы)."""
    m = re.match(r"\s*(\d+)\s*°\s*(\d+)\s*'\s*(\d+(?:\.\d+)?)\s*\"?\s*$", s.strip())
    if not m:
        # Запасной вариант: уже число
        try:
            return float(s)
        except ValueError:
            return 0.0
    d, m_arc, s_arc = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return d + m_arc / 60 + s_arc / 3600


def parse_csv(csv_path: str | Path) -> dict[str, Any]:
    """Парсит CSV формата karta_*.csv. Возвращает {meta, rows}."""
    meta: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    text = Path(csv_path).read_text(encoding="utf-8")
    lines = text.split("\n")

    in_header = True
    for line in lines:
        if not line.strip():
            continue
        if line.startswith("#"):
            m = re.match(r"^#\s*([^;]+);\s*(.+)$", line)
            if m:
                meta[m.group(1).strip()] = m.group(2).strip()
            continue
        if in_header and line.startswith("Планета;"):
            in_header = False
            continue
        if in_header:
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 8:
            continue
        rows.append({
            "planet": parts[0],
            "degree": parts[1],
            "nakshatra": parts[2],
            "house": parts[3],
            "aspect": parts[4],
            "star": parts[5],
            "constellation": parts[6],
            "orb": _parse_orb(parts[7]),
        })
    return {"meta": meta, "rows": rows}


# ---------------------------------------------------------------------------
# Асцендент (детерминированно по градусу)
# ---------------------------------------------------------------------------

def compute_ascendant_data(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Из строк CSV находит асцендент и вычисляет знак + диспозитора.

    Возвращает:
    {
      degree_str: '301°43\\'20"',
      degree_decimal: 301.72,
      nakshatra: 'Дхаништха',
      pada: 3,
      sign: 'Водолей',
      sign_index: 10,
      lord: 'Сатурн',
      house_1: 'Водолей',
      note: 'Знак определён детерминированно по градусу. Накшатры могут пересекать границы знаков, поэтому НЕ используем накшатру для определения знака.'
    }
    """
    asc_row = next((r for r in rows if r["planet"] == "Асцендент"), None)
    if not asc_row:
        return None

    deg = _parse_degree(asc_row["degree"])
    sign_idx = int(deg // 30) % 12
    sign_name, lord = ZODIAC_SIGNS[sign_idx]

    naksh_raw = asc_row.get("nakshatra", "")
    naksh_name = naksh_raw
    pada = None
    if "/" in naksh_raw:
        parts = naksh_raw.split("/")
        naksh_name = parts[0].strip()
        try:
            pada = int(parts[1].strip())
        except (ValueError, IndexError):
            pada = None

    return {
        "degree_str": asc_row["degree"],
        "degree_decimal": round(deg, 4),
        "nakshatra": naksh_name,
        "pada": pada,
        "sign": sign_name,
        "sign_index": sign_idx,
        "lord": lord,
        "house_1": sign_name,
        "note": (
            "Знак асцендента определён детерминированно по градусу. "
            "Накшатры могут пересекать границы знаков (Мригашира: Телец+Близнецы; "
            "Вишакха: Весы+Скорпион), поэтому НЕ используем накшатру для определения знака. "
            "Используем готовое значение sign из этого блока."
        ),
    }


# ---------------------------------------------------------------------------
# Тиры конъюнкций
# ---------------------------------------------------------------------------

def tier_weight(planet: str, star: str, orb: float) -> tuple[float, str, str]:
    """Возвращает (вес, имя_тира, категория).

    Категория:
      - 'main'     — попадает в TIER-таблицу, может быть в Top
      - 'indirect' — на границе, упоминается как «косвенное влияние»
      - 'out'      — игнорируем
    """
    if planet in EXCLUDED_POINTS:
        return 0.0, "OUT", "out"

    is_outer = planet in OUTER_PLANETS

    if is_outer:
        if orb < ORB_OUTER_TIGHT_MAX:
            return 3.0, "TIER0_tight", "main"
        if orb < ORB_OUTER_WIDE_MAX:
            return 3.0, "TIER0_wide", "main"
        if orb < ORB_OUTER_INDIRECT_MAX:
            return 1.0, "TIER0_indirect", "indirect"
        return 0.0, "OUT", "out"

    # Personal / node
    if orb < 0.2:
        base_w, base_t = 3.0, "TIER1"
    elif orb < 1.0:
        base_w, base_t = 2.0, "TIER2"
    elif orb < 2.0:
        base_w, base_t = 1.5, "TIER3"
    elif orb < ORB_REGULAR_INDIRECT_MAX:
        return 0.5, "TIER_indirect", "indirect"
    else:
        return 0.0, "OUT", "out"

    # GC-boost
    if star in GC_POINTS:
        if base_t == "TIER3":
            return 2.0, "TIER2+GC", "main"
        if base_t == "TIER2":
            return 3.0, "TIER1+GC", "main"
        return base_w, base_t + "+GC", "main"

    return base_w, base_t, "main"


def normalize_civ_name(constellation: str, star: str) -> str:
    if star in GC_POINTS:
        return star
    return SKY_GROUPING.get(constellation, constellation)


# ---------------------------------------------------------------------------
# Top-N
# ---------------------------------------------------------------------------

def _assign_priority_group(c: dict[str, Any]) -> str:
    """Назначает группу приоритета по правилам v3.2 (с правилом R7).

    Приоритет (сверху вниз):
      A1                       — multi-contact non-node с TIER0_tight/TIER1
                                 ИЛИ weight ≥ 5.0 (R7.1)
      A_gc_tight               — single conjunction с GC-точкой + узкий орб
      A_personal_t1            — single personal TIER1 non-GC (orb<0.2°)
      A1_multi_personal_mid    — R7.2: ≥ 2 уникальных звезды одной цивилизации
                                 в орбе < 1° любыми планетами (хотя бы одна не узел)
      A_outer_tight            — single outer TIER0 узкий non-GC
      A_nodes_multi            — multi-contact только через узлы (Раху/Кету)
      A_personal_node_trail    — personal orb<1° + узловой шлейф той же цивилизации
      A_gc_wide                — single conjunction с GC-точкой + широкий орб
      A1_low                   — multi-contact non-node без TIER0_tight и TIER1
      B                        — single outer TIER0 широкий non-GC
      C                        — single personal TIER2 non-GC (orb<1°)
      D                        — слабые
    """
    only_nodes = all(p in NODES for p in c["planets"])
    multi_contact = c["count"] >= 2

    # ----- R7.1: тяжёлая цивилизация по сумме весов → A1 (только если не одни узлы) -----
    if not only_nodes and c["weight"] >= 5.0:
        return "A1"

    # ----- R7.2: ≥ 2 уникальных звезды в орбе < 1° любыми не-узловыми планетами -----
    tight_conjs = [cj for cj in c["conjunctions"] if cj["orb"] < 1.0]
    tight_unique_stars = {cj["star"] for cj in tight_conjs}
    non_node_in_tight = any(cj["planet"] not in NODES for cj in tight_conjs)
    has_r7_multi = (
        not only_nodes
        and len(tight_unique_stars) >= 2
        and non_node_in_tight
    )

    is_gc = any(cj["star"] in GC_POINTS for cj in c["conjunctions"])

    has_outer_tight = any(
        cj["planet"] in OUTER_PLANETS and cj["orb"] < ORB_OUTER_TIGHT_MAX
        for cj in c["conjunctions"]
    )
    has_outer_wide = any(
        cj["planet"] in OUTER_PLANETS
        and ORB_OUTER_TIGHT_MAX <= cj["orb"] < ORB_OUTER_WIDE_MAX
        for cj in c["conjunctions"]
    )
    has_tier1_personal = any(
        cj["planet"] not in OUTER_PLANETS
        and cj["planet"] not in NODES
        and cj["orb"] < 0.2
        for cj in c["conjunctions"]
    )
    has_tier2_personal = any(
        cj["planet"] not in OUTER_PLANETS
        and cj["planet"] not in NODES
        and 0.2 <= cj["orb"] < 1.0
        for cj in c["conjunctions"]
    )

    if multi_contact and not only_nodes:
        if has_outer_tight or has_tier1_personal:
            return "A1"
        # R7.2 имеет приоритет над A1_low — это «multi-contact но слабее A1»
        if has_r7_multi:
            return "A1_multi_personal_mid"
        return "A1_low"

    if is_gc and (has_outer_tight or has_tier1_personal):
        return "A_gc_tight"

    if has_tier1_personal and not is_gc:
        return "A_personal_t1"

    # R7.2 — между A_personal_t1 и A_outer_tight
    if has_r7_multi:
        return "A1_multi_personal_mid"

    if has_outer_tight and not is_gc:
        return "A_outer_tight"

    if multi_contact and only_nodes:
        return "A_nodes_multi"

    if is_gc:
        return "A_gc_wide"

    if has_outer_wide:
        return "B"

    if has_tier2_personal:
        return "C"

    return "D"


def _has_personal_node_trail(c: dict[str, Any], indirect: dict[str, Any] | None) -> bool:
    """R8: точная личная планета + узловой шлейф той же цивилизации.

    Условия:
    - в основном списке есть личная планета в орбе < 1°;
    - в indirect по той же цивилизации есть Раху или Кету в орбе 2°..3°.

    Это ловит не одиночную "кармическую" точку, а живую линию, где личная
    планета уже включила цивилизацию, а узел показывает вектор/шлейф.
    """
    has_tight_personal = any(
        cj["planet"] not in OUTER_PLANETS
        and cj["planet"] not in NODES
        and cj["orb"] < 1.0
        for cj in c["conjunctions"]
    )
    if not has_tight_personal or not indirect:
        return False
    return any(
        cj["planet"] in NODES
        and ORB_REGULAR_MAX <= cj["orb"] < ORB_NODE_TRAIL_MAX
        for cj in indirect.get("conjunctions", [])
    )


def _node_trail_conjunctions(indirect: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not indirect:
        return []
    return [
        cj
        for cj in indirect.get("conjunctions", [])
        if cj["planet"] in NODES
        and ORB_REGULAR_MAX <= cj["orb"] < ORB_NODE_TRAIL_MAX
    ]


def compute_top_civilizations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Считает Top-3 цивилизаций + косвенные + nodes_only + асцендент."""
    by_civ: dict[str, dict[str, Any]] = {}
    by_civ_indirect: dict[str, dict[str, Any]] = {}
    tier_table: list[dict[str, Any]] = []

    for r in rows:
        if r["aspect"] != "Соединение":
            continue
        weight, tier, category = tier_weight(r["planet"], r["star"], r["orb"])
        if category == "out":
            continue

        civ = normalize_civ_name(r["constellation"], r["star"])

        target = by_civ if category == "main" else by_civ_indirect
        rec = target.setdefault(civ, {
            "civilization": civ,
            "weight": 0.0,
            "count": 0,
            "min_orb": 999.0,
            "planets": set(),
            "conjunctions": [],
            "has_outer": False,
            "has_tight": False,
        })
        rec["weight"] += weight
        rec["count"] += 1
        rec["min_orb"] = min(rec["min_orb"], r["orb"])
        rec["planets"].add(r["planet"])
        if r["planet"] in OUTER_PLANETS:
            rec["has_outer"] = True
        if r["orb"] < 0.2:
            rec["has_tight"] = True
        rec["conjunctions"].append({
            "planet": r["planet"],
            "star": r["star"],
            "orb": r["orb"],
            "house": r["house"],
            "tier": tier,
            "weight": weight,
        })

        if category == "main":
            tier_table.append({
                "planet": r["planet"],
                "star": r["star"],
                "constellation": r["constellation"],
                "orb": r["orb"],
                "house": r["house"],
                "weight": weight,
                "tier": tier,
            })

    # Eligibility для Top
    eligible: list[dict[str, Any]] = []
    for c in by_civ.values():
        unique_stars = {cj["star"] for cj in c["conjunctions"]}
        c["unique_stars_count"] = len(unique_stars)
        c["priority_group"] = _assign_priority_group(c)
        if (
            c["priority_group"] in {"B", "C", "D", "A1_low"}
            and _has_personal_node_trail(c, by_civ_indirect.get(c["civilization"]))
        ):
            c["priority_group"] = "A_personal_node_trail"
            c["node_trail_boost"] = True
            c["node_trail_conjunctions"] = _node_trail_conjunctions(
                by_civ_indirect.get(c["civilization"])
            )
        eligible.append(c)

    group_rank = {
        "A1": 0,
        "A_gc_tight": 1,
        "A_personal_t1": 2,
        "A1_multi_personal_mid": 2.5,   # R7.2 v3.2
        "A_outer_tight": 3,
        "A_nodes_multi": 4,
        "A_personal_node_trail": 4.5,    # R8 v3.3
        "A_gc_wide": 5,
        "A1_low": 6,
        "B": 7,
        "C": 8,
        "D": 9,
    }
    eligible.sort(key=lambda x: (
        group_rank.get(x["priority_group"], 99),
        -x["weight"],
        x["min_orb"],
    ))

    top = eligible[:TOP_N]
    other = eligible[TOP_N:]

    # Nodes_only оставляем отдельным списком для блока «направление эволюции».
    # Цивилизация попадает в nodes_only если она только из узлов И не вошла в Top.
    nodes_only: list[dict[str, Any]] = []
    for c in eligible:
        only_nodes = all(p in NODES for p in c["planets"])
        if only_nodes and c not in top:
            nodes_only.append(c)

    # Косвенные цивилизации (orb 2-5° personal/node, 5-10° outer)
    indirect: list[dict[str, Any]] = []
    main_civs_in_top = {c["civilization"] for c in top}
    for c in by_civ_indirect.values():
        # Если эта же цивилизация уже представлена основным соединением — пропускаем
        if c["civilization"] in main_civs_in_top:
            continue
        unique_stars = {cj["star"] for cj in c["conjunctions"]}
        c["unique_stars_count"] = len(unique_stars)
        indirect.append(c)
    indirect.sort(key=lambda x: x["min_orb"])

    # Возраст души
    total_main_conj = len(tier_table)
    soul_age = "древняя" if total_main_conj >= 5 else "молодая"

    # planets → list для сериализации
    for c in eligible + nodes_only + indirect:
        c["planets"] = sorted(c["planets"])

    ascendant = compute_ascendant_data(rows)

    return {
        "top": top,
        "ranked_full": eligible,
        "other": other,
        "total_conjunctions": total_main_conj,
        "soul_age": soul_age,
        "top_n": TOP_N,
        "nodes_only_civilizations": nodes_only,
        "indirect_civilizations": indirect,
        "tier_table": tier_table,
        "ascendant": ascendant,
    }


# ---------------------------------------------------------------------------
# Рендер для логов
# ---------------------------------------------------------------------------

def render_top_md(top_data: dict[str, Any]) -> str:
    lines = []
    asc = top_data.get("ascendant")
    if asc:
        lines.append(
            f"Асцендент (вычислено по градусу): {asc['degree_str']} → "
            f"{asc['sign']} (управитель: {asc['lord']}), накшатра {asc['nakshatra']}/{asc['pada']}"
        )
        lines.append("")

    lines.append(f"Всего значимых соединений: {top_data['total_conjunctions']}")
    lines.append(f"Возраст души: {top_data['soul_age']}")
    lines.append(f"Топ-{top_data['top_n']} цивилизаций:")

    for i, c in enumerate(top_data["top"], 1):
        conjs = " · ".join(
            f"{cj['planet']} ☌ {cj['star']} {cj['orb']:.2f}° ({cj['tier']})"
            for cj in c["conjunctions"]
        )
        if c.get("node_trail_conjunctions"):
            trail = " · ".join(
                f"{cj['planet']} ☌ {cj['star']} {cj['orb']:.2f}° ({cj['tier']}, шлейф)"
                for cj in c["node_trail_conjunctions"]
            )
            conjs = f"{conjs} · {trail}"
        lines.append(
            f"  {i}. {c['civilization']} — вес {c['weight']:.2f} | "
            f"{c['count']} соед. | гр.{c['priority_group']} | "
            f"min_orb {c['min_orb']:.2f}° | {conjs}"
        )

    if top_data.get("indirect_civilizations"):
        lines.append("")
        lines.append("Косвенные цивилизации (упомянуть как «косвенное влияние», не основная линия):")
        for c in top_data["indirect_civilizations"]:
            for cj in c["conjunctions"]:
                lines.append(
                    f"  ~ {cj['planet']} ☌ {cj['star']} {cj['orb']:.2f}° "
                    f"(созвездие: {c['civilization']}, {cj['tier']})"
                )

    if top_data["nodes_only_civilizations"]:
        lines.append("")
        lines.append("Соединения только узлов вне Top (направление эволюции / макс. опыт):")
        for c in top_data["nodes_only_civilizations"]:
            for cj in c["conjunctions"]:
                lines.append(
                    f"  {cj['planet']} ☌ {cj['star']} {cj['orb']:.2f}° "
                    f"(созвездие {c['civilization']}, {cj['tier']})"
                )

    if top_data.get("tier_table"):
        lines.append("")
        lines.append("Полная TIER-таблица соединений:")
        for t in sorted(top_data["tier_table"], key=lambda x: x["orb"]):
            lines.append(
                f"  {t['planet']:10s} ☌ {t['star']:30s} ({t['constellation']:20s}) "
                f"orb {t['orb']:.2f}° | {t['tier']:15s} ×{t['weight']}"
            )

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: tier_calculator.py <path_to_karta.csv>")
        sys.exit(1)

    parsed = parse_csv(sys.argv[1])
    print(f"=== META: {parsed['meta'].get('Дата рождения')} {parsed['meta'].get('Город')} ===")
    print(f"=== ROWS: {len(parsed['rows'])} ===\n")
    top = compute_top_civilizations(parsed["rows"])
    print(render_top_md(top))
