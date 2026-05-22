"""compare_versions.py — человекочитаемый diff raw vs v2 разбора.

Создаёт `changes_report.md` в папке клиента: что именно изменила Кайя
относительно AI-разбора от агента. Нужно для аудита Дарьей.

Использование:
    python .cursor/skills/3-validation/compare_versions.py "<путь_к_папке_клиента>"

Что выдаёт:
- кол-во добавленных / удалённых / изменённых строк
- секции, которые были перестроены (по заголовкам ## и ###)
- топ-10 самых длинных удалённых блоков (что Кайя вырезала)
- топ-10 самых длинных добавленных блоков (что Кайя дописала)
- сводка по изменению ссылок (услуги, книга, WhatsApp)

Это НЕ полный unified diff (он слишком большой для человека) —
а компактная сводка «что было сделано».
"""

import difflib
import re
import sys
from pathlib import Path


def extract_headers(text: str) -> list[str]:
    """Извлекает все ## и ### заголовки в порядке появления."""
    return re.findall(r"^#{2,3}\s+.+$", text, re.M)


def extract_links(text: str) -> dict[str, int]:
    """Считает упоминания ключевых ссылок."""
    return {
        "энергодуш": len(re.findall(r"\[\s*[ЭэEе]нергодуш", text)),
        "тотальная_консультация": len(re.findall(r"\[\s*[Тт]отальн", text)),
        "сопровождение": len(re.findall(r"\[\s*[Сс]опровожден", text)),
        "книга": len(re.findall(r"Активация Внеземной ДНК", text)),
        "книга_с_ссылкой": len(re.findall(r"\[«Активация Внеземной ДНК»\]\(https://intergalactic-astrology\.com/book/", text)),
        "whatsapp_cta": len(re.findall(r"wa\.me/message/X6MQ6PLPR7K4L1", text)),
    }


def compare(folder: Path) -> str:
    raw_candidates = [p for p in folder.glob("*_миссия.md") if "_v2" not in p.stem]
    v2_candidates = list(folder.glob("*_миссия_v2.md"))

    if not raw_candidates:
        return f"  Raw файл *_миссия.md не найден в {folder}\n"
    if not v2_candidates:
        return f"  v2 файл *_миссия_v2.md не найден в {folder}\n"

    raw_path = raw_candidates[0]
    v2_path = v2_candidates[0]

    raw_text = raw_path.read_text(encoding="utf-8")
    v2_text = v2_path.read_text(encoding="utf-8")

    raw_lines = raw_text.splitlines()
    v2_lines = v2_text.splitlines()

    # difflib summary
    diff = list(difflib.unified_diff(raw_lines, v2_lines, n=0, lineterm=""))
    added = [l[1:] for l in diff if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:] for l in diff if l.startswith("-") and not l.startswith("---")]

    # Длинные блоки (фильтр по длине > 50 символов)
    long_removed = sorted([l for l in removed if len(l.strip()) > 50], key=len, reverse=True)[:10]
    long_added = sorted([l for l in added if len(l.strip()) > 50], key=len, reverse=True)[:10]

    # Заголовки
    raw_headers = extract_headers(raw_text)
    v2_headers = extract_headers(v2_text)
    removed_headers = [h for h in raw_headers if h not in v2_headers]
    added_headers = [h for h in v2_headers if h not in raw_headers]

    # Ссылки
    raw_links = extract_links(raw_text)
    v2_links = extract_links(v2_text)

    # Сборка отчёта
    rep = []
    rep.append("# changes_report")
    rep.append("")
    rep.append(f"Сравнение: `{raw_path.name}` (raw от агента) vs `{v2_path.name}` (доработка Кайи).")
    rep.append("")
    rep.append("## Сводка по строкам")
    rep.append("")
    rep.append(f"| Метрика | Raw | v2 | Δ |")
    rep.append(f"|---|---|---|---|")
    rep.append(f"| Всего строк | {len(raw_lines)} | {len(v2_lines)} | {len(v2_lines) - len(raw_lines):+d} |")
    rep.append(f"| Удалено строк (raw → v2) | — | — | {len(removed)} |")
    rep.append(f"| Добавлено строк (raw → v2) | — | — | {len(added)} |")
    rep.append("")
    rep.append("## Сводка по ссылкам и упоминаниям")
    rep.append("")
    rep.append("| Что | Raw | v2 | Δ |")
    rep.append("|---|---|---|---|")
    for k in raw_links:
        delta = v2_links[k] - raw_links[k]
        sign = f"{delta:+d}" if delta != 0 else "0"
        rep.append(f"| {k} | {raw_links[k]} | {v2_links[k]} | {sign} |")
    rep.append("")

    if removed_headers:
        rep.append("## Удалённые заголовки (Кайя убрала эти разделы)")
        rep.append("")
        for h in removed_headers[:15]:
            rep.append(f"- ~~{h.strip()}~~")
        rep.append("")

    if added_headers:
        rep.append("## Добавленные заголовки (Кайя дописала эти разделы)")
        rep.append("")
        for h in added_headers[:15]:
            rep.append(f"- **{h.strip()}**")
        rep.append("")

    if long_removed:
        rep.append("## Топ-10 крупных удалённых блоков")
        rep.append("")
        for ln in long_removed:
            snippet = ln.strip()[:200]
            rep.append(f"- ~~{snippet}{'…' if len(ln.strip()) > 200 else ''}~~")
        rep.append("")

    if long_added:
        rep.append("## Топ-10 крупных добавленных блоков")
        rep.append("")
        for ln in long_added:
            snippet = ln.strip()[:200]
            rep.append(f"- {snippet}{'…' if len(ln.strip()) > 200 else ''}")
        rep.append("")

    rep.append("---")
    rep.append("")
    rep.append("Сгенерировано `.cursor/skills/3-validation/compare_versions.py`")

    return "\n".join(rep)


def main():
    if len(sys.argv) < 2:
        print("Использование: python compare_versions.py <путь_к_папке_клиента>")
        sys.exit(1)

    folder = Path(sys.argv[1])
    if not folder.exists():
        print(f"  Папка не найдена: {folder}")
        sys.exit(1)

    report = compare(folder)
    out_path = folder / "changes_report.md"
    out_path.write_text(report, encoding="utf-8")

    print(f"  ✓ Отчёт сохранён: {out_path}")
    print()
    print(report[:1500])
    if len(report) > 1500:
        print("...")
    sys.exit(0)


if __name__ == "__main__":
    main()
