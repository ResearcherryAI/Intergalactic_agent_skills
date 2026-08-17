#!/usr/bin/env python3
"""
Калькулятор профессий для разбора ДНК денег.

Алгоритм (установлен 19.06.2026):
  1) НАКШАТРА планеты — первичный определитель профессии
  2) Есть ли СОЕДИНЕНИЕ со звездой/цивилизацией?
       да  -> добавить профессии из звезды (с учётом дома)
       нет -> пропустить
  3) ДОМ — сфера дохода
  4) Соединения и стеллиумы — связки планет
  5) ПОВТОРЫ — профессии/темы, встречающиеся в 2+ слоях или у 2+ планет =
     наиболее вероятные для человека.

Знак НЕ используется (убран в архив _archive/money_planet_sign_professions.md).

Использование:
  python .cursor/skills/2-money-analysis/calc_professions.py "путь/к/karta.csv"
"""
import sys
import io
import csv
import json
import re
from pathlib import Path
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
MASTER = SCRIPT_DIR / "professions_master.json"

# Финансовые планеты — для них считаем профессии (порядок = приоритет вывода)
MONEY_PLANETS = ["Юпитер", "Сатурн", "Венера", "Меркурий", "Солнце", "Луна",
                 "Марс", "Асцендент", "Раху", "Кету", "Уран", "Нептун", "Плутон"]


def normalize(s):
    s = s.lower().replace("ё", "е").replace("-", "").replace(" ", "")
    return s.strip()


def find_key(name, keys):
    """Сопоставление имени из CSV с ключом в JSON (звёзды/накшатры)."""
    n = normalize(name)
    for key in keys:
        if normalize(key) == n:
            return key
    best = None
    for key in keys:
        nk = normalize(key)
        if n.startswith(nk) or nk.startswith(n):
            if best is None or len(normalize(key)) > len(normalize(best)):
                best = key
    return best


def main():
    if len(sys.argv) < 2:
        print("Использование: python calc_professions.py <путь_к_csv>")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"ERROR: файл не найден: {csv_path}")
        sys.exit(1)

    data = json.load(open(MASTER, encoding="utf-8"))
    nakshatras = data["nakshatras"]
    stars = data["stars"]
    houses = data["houses"]

    # Парсим CSV: собираем строки по планетам
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("Планета;"):
                continue
            parts = line.split(";")
            if len(parts) < 8:
                continue
            rows.append({
                "planet": parts[0].strip(),
                "degree": parts[1].strip(),
                "nakshatra": parts[2].strip(),
                "house": parts[3].strip(),
                "aspect": parts[4].strip(),
                "star": parts[5].strip(),
                "constellation": parts[6].strip(),
                "orb": parts[7].strip(),
            })

    # Группируем по планете
    by_planet = defaultdict(list)
    for r in rows:
        by_planet[r["planet"]].append(r)

    # Глобальный счётчик профессий (для блока ПОВТОРЫ)
    global_prof = Counter()
    # Источник каждой профессии (планета+слой) — для отчёта
    prof_sources = defaultdict(set)

    print("=" * 70)
    print(f"  ПРОФЕССИИ ПО КАРТЕ: {csv_path.name}")
    print("=" * 70)

    for planet in MONEY_PLANETS:
        if planet not in by_planet:
            continue
        entries = by_planet[planet]
        first = entries[0]
        nak_full = first["nakshatra"]          # напр. "Мула/2"
        nak = nak_full.split("/")[0].strip()    # "Мула"
        house = first["house"]

        print(f"\n{'─'*70}")
        print(f"  {planet.upper()} — {nak_full}, {house}-й дом")
        print(f"{'─'*70}")

        planet_profs = set()

        # СЛОЙ 1: накшатра
        nak_key = find_key(nak, nakshatras)
        if nak_key:
            nk = nakshatras[nak_key]
            nak = nak_key
            profs = nk["professions"]
            print(f"  [1] НАКШАТРА {nak} ({nk['shakti']}):")
            print(f"      {', '.join(profs)}")
            for p in profs:
                planet_profs.add(p)
                prof_sources[p].add(f"{planet}:накшатра")
        else:
            print(f"  [1] НАКШАТРА {nak}: НЕ НАЙДЕНА в справочнике")

        # СЛОЙ 2: соединения со звёздами
        conjunctions = [e for e in entries if "оединение" in e["aspect"]]
        if conjunctions:
            for c in conjunctions:
                skey = find_key(c["star"], stars)
                if skey:
                    st = stars[skey]
                    profs = list(st["professions"])
                    note = st.get("house_notes", {}).get(house, "")
                    print(f"  [2] ☌ {c['star']} ({c['orb']}°) — {st['archetype']}:")
                    print(f"      {', '.join(profs)}")
                    if note:
                        print(f"      дом {house}: {note}")
                    for p in profs:
                        planet_profs.add(p)
                        prof_sources[p].add(f"{planet}:звезда({skey})")
                else:
                    print(f"  [2] ☌ {c['star']} ({c['orb']}°) — нет в справочнике звёзд "
                          f"(взять из library_compact.json)")
        else:
            print(f"  [2] СОЕДИНЕНИЙ нет — пропуск слоя звёзд")

        # СЛОЙ 3: дом
        if house in houses:
            h = houses[house]
            print(f"  [3] ДОМ {house}: {h['sphere']}")
            print(f"      деньги: {h['money']}")

        # учёт в глобальном счётчике
        for p in planet_profs:
            global_prof[p] += 1

    # БЛОК ПОВТОРОВ
    print(f"\n{'='*70}")
    print("  ПОВТОРЫ — профессии, встречающиеся у 2+ планет (наиболее вероятные)")
    print(f"{'='*70}")
    repeats = [(p, c) for p, c in global_prof.most_common() if c >= 2]
    if repeats:
        for p, c in repeats:
            srcs = ", ".join(sorted(prof_sources[p]))
            print(f"  {c}× {p}  ←  {srcs}")
    else:
        print("  Прямых повторов профессий нет — смотри пересечения по ТЕМАМ "
              "(руководство, диагностика, обучение и т.п.) вручную.")

    print(f"\n{'='*70}")
    print("  ИТОГ: выбери 10 профессий + 1 объединяющую.")
    print("  Приоритет: ПОВТОРЫ > звезда(соединение) > накшатра ведущих планет.")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
