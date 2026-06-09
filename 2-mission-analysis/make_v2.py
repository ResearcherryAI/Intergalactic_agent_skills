"""make_v2.py — клонировать raw AI-разбор в v2 и применить базовые механистические правки.

Что делает:
1. Находит raw `<Имя>_<DDMMYYYY>_миссия.md` в папке клиента
2. Если v2 уже существует — выводит warning и не перезаписывает
3. Клонирует raw → `<Имя>_<DDMMYYYY>_миссия_v2.md`
4. Применяет автоматические правки самых механистических fail-ов:
   • E1: убирает «бесплатно»
   • E2: убирает Vimshottari/Вимшоттари/махадаша
   • B2: меняет «Дарья Лачинова»/«Лачинова» → «Кайя Каэн»
   • B3: оборачивает первые 2 «Активация Внеземной ДНК» без ссылки в гиперссылку
   • E6: убирает токены TIER/гр.A1/вес×3 из нарратива
   • A8: помечает лишние «практики цивилизаций» как кандидатов на удаление (комментарием HTML)
5. Сохраняет v2 + печатает diff-сводку «что было сделано автоматически»

Смысловые правки (Топ-3, тени, профессии, выдуманные аспекты) — ВРУЧНУЮ Кайей по карте правок из 2-analysis/SKILL.md.

Usage:
    python .cursor/skills/2-analysis/make_v2.py "<путь_к_папке_клиента>"

Output:
    Создаёт `<Имя>_<DDMMYYYY>_миссия_v2.md` рядом с raw.
    Печатает список применённых автоправок.

Exit code: 0 = ok, 1 = raw не найден, 2 = v2 уже есть
"""

import re
import sys
from pathlib import Path


BOOK_LINK = "[«Активация Внеземной ДНК»](https://intergalactic-astrology.com/book/)"


def auto_fix(text: str) -> tuple[str, list[str]]:
    """Применить автоматические правки. Возвращает (новый_текст, список_изменений)."""
    fixes: list[str] = []
    out = text

    # E1: убираем «бесплатно»
    if re.search(r"\bбесплатно\b", out, re.I):
        out = re.sub(r"\bбесплатно\b", "", out, flags=re.I)
        out = re.sub(r" +", " ", out)
        fixes.append("E1: удалено слово «бесплатно»")

    # E2: убираем Vimshottari/Вимшоттари/махадаша
    e2_patterns = [
        (r"\bVimshottari\b", "[период развития]"),
        (r"\bВимшоттари\b", "[период развития]"),
        (r"\bмахадаш[аи]\b", "[период]"),
        (r"\bМД\s*/\s*АД\b", "[периоды]"),
    ]
    e2_count = 0
    for p, repl in e2_patterns:
        new_out, n = re.subn(p, repl, out, flags=re.I)
        if n > 0:
            out = new_out
            e2_count += n
    if e2_count:
        fixes.append(f"E2: заменено {e2_count} вхождений Vimshottari/махадаша на нейтральные термины")

    # B2: «Дарья Лачинова» / «Лачинова» → «Кайя Каэн»
    b2_count = 0
    for p in (r"Дарья\s+Лачинова", r"Лачинова"):
        new_out, n = re.subn(p, "Кайя Каэн", out)
        if n > 0:
            out = new_out
            b2_count += n
    if b2_count:
        fixes.append(f"B2: заменено {b2_count} «Лачинова» на «Кайя Каэн»")

    # B3: оборачиваем «Активация Внеземной ДНК» без ссылки в гиперссылку (первые 2 вхождения)
    b3_count = 0
    def _wrap_book(m: re.Match) -> str:
        nonlocal b3_count
        if b3_count >= 5:
            return m.group(0)
        # Уже в гиперссылке?
        start = max(0, m.start() - 2)
        if out[start:m.start()] == "](" or "](https://intergalactic-astrology.com/book/" in out[m.start():m.end()+50]:
            return m.group(0)
        b3_count += 1
        return BOOK_LINK

    # Ищем «Активация Внеземной ДНК» НЕ внутри []
    pattern = re.compile(r"«Активация Внеземной ДНК»")
    new_parts = []
    last = 0
    for m in pattern.finditer(out):
        prev = out[max(0, m.start() - 1):m.start()]
        next_chunk = out[m.end():m.end() + 60]
        if prev == "[" or next_chunk.startswith("](https://intergalactic-astrology.com/book/"):
            new_parts.append(out[last:m.end()])
            last = m.end()
            continue
        new_parts.append(out[last:m.start()])
        new_parts.append(BOOK_LINK)
        last = m.end()
        b3_count += 1
    new_parts.append(out[last:])
    if b3_count:
        out = "".join(new_parts)
        fixes.append(f"B3: обёрнуто в гиперссылку {b3_count} упоминаний книги")

    # E6: токены TIER/гр.A1/вес×N/orb в нарративе
    e6_count = 0
    e6_patterns = [
        (r"\bTIER\s*\d?\b", ""),
        (r"гр\.\s*A\d", ""),
        (r"вес\s*[×x]\s*\d+(?:\.\d+)?", ""),
        (r"\borb[ы]?\s*[:=]\s*\d+(?:\.\d+)?°?", ""),
    ]
    for p, repl in e6_patterns:
        new_out, n = re.subn(p, repl, out, flags=re.I)
        if n > 0:
            out = new_out
            e6_count += n
    if e6_count:
        out = re.sub(r" +", " ", out)
        out = re.sub(r"\(\s*[,;]\s*\)", "", out)
        out = re.sub(r"\(\s*\)", "", out)
        fixes.append(f"E6: удалено {e6_count} технических токенов (TIER/orb/вес)")

    # E7: помечаем «практики цивилизаций» как кандидатов на удаление
    e7_patterns = [
        r"практик[аи]\s+(?:для\s+)?активации\s+линии",
        r"утренний огонь",
        r"практик[аи]\s+отпускания",
        r"активаци[яи]\s+линии\s+цивилизаци",
    ]
    e7_count = 0
    for p in e7_patterns:
        for m in re.finditer(p, out, re.I):
            e7_count += 1
    if e7_count:
        fixes.append(f"E7: ⚠️ найдено {e7_count} лишних практик — УБРАТЬ ВРУЧНУЮ (НЕ автоудаляю, чтобы не оторвать соседний абзац)")

    return out, fixes


def main():
    if len(sys.argv) < 2:
        print("Использование: python make_v2.py <путь_к_папке_клиента>")
        sys.exit(1)

    folder = Path(sys.argv[1])
    if not folder.exists():
        print(f"  Папка не найдена: {folder}")
        sys.exit(1)

    raw_candidates = [p for p in folder.glob("*_миссия.md") if "_v2" not in p.stem]
    if not raw_candidates:
        print(f"  Raw файл *_миссия.md не найден в {folder}")
        sys.exit(1)
    raw_path = raw_candidates[0]

    v2_path = raw_path.with_name(raw_path.stem + "_v2.md")
    if v2_path.exists():
        print(f"  ⚠️ v2 уже существует: {v2_path.name}")
        print(f"     удалите его вручную, если хотите пересоздать")
        sys.exit(2)

    raw_text = raw_path.read_text(encoding="utf-8")
    v2_text, fixes = auto_fix(raw_text)
    v2_path.write_text(v2_text, encoding="utf-8")

    print(f"  ✓ Создан v2: {v2_path.name}")
    print(f"     ({len(raw_text)} → {len(v2_text)} символов)")

    if fixes:
        print(f"\n  Применённые автоправки ({len(fixes)}):")
        for f in fixes:
            print(f"    • {f}")
    else:
        print("\n  Автоправок не применилось (raw уже чистый по механике)")

    print(f"\n  СЛЕДУЮЩИЙ ШАГ:")
    print(f"    python .cursor/skills/3-validation/benchmark.py \"{v2_path}\" \"Top1,Top2,Top3\" --json")
    print(f"  Затем точечно править v2 по карте правок из 2-analysis/SKILL.md")
    sys.exit(0)


if __name__ == "__main__":
    main()
