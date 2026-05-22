"""
verify_aspects.py — Верификация аспектов в MD-файле клиента по CSV.

Проверяет, что каждый аспект (секстиль, трин, квадрат, оппозиция),
упомянутый в тексте _миссия.md, реально существует в CSV-карте клиента.

Использование:
    python .cursor/skills/3-validation/verify_aspects.py "путь_к_папке_клиента"

Пример:
    python .cursor/skills/3-validation/verify_aspects.py "D:\\DariaGalactic\\Профайлы клиентов\\Купившие разбор\\Елена_795784ccc0d7_20260521"

Выход:
    ✓ Все аспекты верифицированы (N из N)
    ✗ ОШИБКА: N аспектов не найдены в CSV — список

Exit code: 0 = OK, 1 = есть ошибки
"""

import re
import sys
import csv
import os
from pathlib import Path


def load_csv_aspects(csv_path: str) -> list[dict]:
    """Читает CSV и возвращает список всех аспектов (кроме соединений)."""
    aspects = []
    with open(csv_path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
    
    if not lines:
        return aspects
    
    reader = csv.DictReader(lines, delimiter=";")
    for row in reader:
        aspect_type = row.get("Аспект", "").strip()
        if aspect_type in ("Секстиль", "Трин", "Квадрат", "Оппозиция"):
            aspects.append({
                "planet": row.get("Планета", "").strip(),
                "type": aspect_type,
                "star": row.get("Звезда", "").strip(),
                "orb": float(row.get("Орбис", "99").replace(",", ".")),
                "constellation": row.get("Созвездие", "").strip(),
            })
    return aspects


def extract_md_aspects(md_path: str) -> list[dict]:
    """Извлекает из MD все упоминания аспектов с планетой, типом и звездой."""
    with open(md_path, encoding="utf-8") as f:
        text = f.read()

    pattern = re.compile(
        r"(Солнце|Луна|Меркурий|Венера|Марс|Юпитер|Сатурн|Уран|Нептун|Плутон|Раху|Кету|Асцендент)"
        r"\s+в\s+(секстиле|трине|квадрате|оппозиции)\s+к\s+"
        r"([^(]+?)\s*\(([^,)]+),?\s*(\d+[.,]\d+)°\)",
        re.IGNORECASE
    )

    type_map = {
        "секстиле": "Секстиль",
        "трине": "Трин",
        "квадрате": "Квадрат",
        "оппозиции": "Оппозиция",
    }

    found = []
    for m in pattern.finditer(text):
        planet = m.group(1).strip()
        aspect = type_map.get(m.group(2).lower(), m.group(2))
        star = m.group(3).strip()
        orb = float(m.group(5).replace(",", "."))
        found.append({
            "planet": planet,
            "type": aspect,
            "star": star,
            "orb": orb,
            "line": text[:m.start()].count("\n") + 1,
            "raw": m.group(0)[:80],
        })
    return found


def normalize(s: str) -> str:
    """Нормализует название для сравнения."""
    s = s.lower().strip()
    replacements = {
        "кольцевая туманность (m57)": "кольцевая туманность (m57)",
        "кольцевой туманности m57": "кольцевая туманность (m57)",
        "m57": "кольцевая туманность (m57)",
        "великому аттрактору": "великий аттрактор",
        "великий аттрактор": "великий аттрактор",
        "сверхгалактическому центру": "сверх-галактический центр",
        "сверх-галактическому центру": "сверх-галактический центр",
        "сверхгалактический центр": "сверх-галактический центр",
        "аттрактору шепли": "аттрактор шепли",
        "аттрактор шепли": "аттрактор шепли",
        "фомальгауту": "фомальгаут",
        "туманности ориона (m42)": "туманность ориона (m42)",
        "туманности ориона": "туманность ориона (m42)",
    }
    for k, v in replacements.items():
        if k in s:
            return v
    if s.endswith("у") or s.endswith("е"):
        s = s[:-1]
    return s


def verify(folder: str) -> tuple[int, int, list[str]]:
    """Проверяет MD vs CSV. Возвращает (total, ok, errors)."""
    folder_path = Path(folder)
    
    csv_files = list(folder_path.glob("karta_*.csv"))
    if not csv_files:
        csv_files = list(folder_path.glob("*.csv"))
    if not csv_files:
        return 0, 0, ["CSV-файл не найден в папке"]

    md_files = list(folder_path.glob("*_миссия.md"))
    if not md_files:
        return 0, 0, ["MD-файл миссии не найден в папке"]

    csv_aspects = load_csv_aspects(str(csv_files[0]))
    md_aspects = extract_md_aspects(str(md_files[0]))

    if not md_aspects:
        return 0, 0, []

    errors = []
    ok_count = 0

    for md_asp in md_aspects:
        matched = False
        md_planet = md_asp["planet"].lower()
        md_type = md_asp["type"]
        md_star = normalize(md_asp["star"])

        for csv_asp in csv_aspects:
            csv_planet = csv_asp["planet"].lower()
            csv_star = normalize(csv_asp["star"])
            
            if csv_planet == md_planet and csv_asp["type"] == md_type:
                if md_star == csv_star or md_star in csv_star or csv_star in md_star:
                    if abs(csv_asp["orb"] - md_asp["orb"]) <= 0.15:
                        matched = True
                        break
                    else:
                        errors.append(
                            f"  строка {md_asp['line']}: {md_asp['raw']}... — ОРБ НЕ СОВПАДАЕТ "
                            f"(в тексте {md_asp['orb']:.2f}°, в CSV {csv_asp['orb']:.2f}°)"
                        )
                        matched = True
                        break

        if not matched:
            errors.append(
                f"  строка {md_asp['line']}: {md_asp['raw']}... — НЕТ В CSV"
            )
        else:
            if not any(f"строка {md_asp['line']}" in e for e in errors):
                ok_count += 1

    return len(md_aspects), ok_count, errors


def main():
    if len(sys.argv) < 2:
        print("Использование: python verify_aspects.py <путь_к_папке_клиента>")
        sys.exit(1)

    folder = sys.argv[1]
    total, ok, errors = verify(folder)

    if not total and not errors:
        print("  Аспектов в тексте не найдено (или файлы не найдены).")
        sys.exit(0)

    if errors and total == 0:
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    print(f"\n  Аспектов в тексте: {total}")
    print(f"  Верифицировано: {ok}")
    print(f"  Ошибок: {len(errors)}")

    if errors:
        print("\n  ✗ ОШИБКИ:")
        for e in errors:
            print(e)
        sys.exit(1)
    else:
        print(f"\n  ✓ Все {total} аспектов верифицированы по CSV.")
        sys.exit(0)


if __name__ == "__main__":
    main()
