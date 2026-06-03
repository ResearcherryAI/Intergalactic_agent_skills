#!/usr/bin/env python3
"""
generate_money_pdf.py — генерация стильного PDF из MD-разбора ДНК денег.

Использует CSS-шаблон от generate_pdf.py (тот же, что для миссий), но БЕЗ
вызова split_service_client (у денег нет блоков «СТРУКТУРА ДНК»/«АНАЛИЗ МИССИИ»).
Заголовок верхнего колонтитула — про ДНК денег.

Запуск:
    python generate_money_pdf.py -i "<папка>/<Имя>_<DDMMYYYY>_деньги.md"
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from generate_pdf import (
    CHROME,
    PROFILES_DIR,
    embed_images_as_base64,
    html_to_pdf,
    inject_styles,
    md_to_html,
)


def main():
    parser = argparse.ArgumentParser(
        description="Генерация стильного PDF из MD-разбора ДНК денег"
    )
    parser.add_argument("--input", "-i", type=Path, required=True,
                        help="Markdown-файл разбора денег")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="PDF (по умолчанию — рядом с .md)")
    parser.add_argument("--header", type=str,
                        default="intergalactic-astrology.com  ·  Kaya Kaen  ·  ДНК Денег",
                        help="Текст верхнего колонтитула")
    parser.add_argument("--keep-html", action="store_true",
                        help="Сохранить промежуточный HTML рядом с PDF")
    args = parser.parse_args()

    md_path = args.input if args.input.is_absolute() else PROFILES_DIR / args.input
    if not md_path.exists():
        print(f"ERROR: {md_path} не найден")
        return 1

    pdf_path = args.output or md_path.with_suffix(".pdf")
    print(f"  Источник : {md_path}")
    print(f"  Результат: {pdf_path}")

    print("\n1. MD → HTML (pandoc)...")
    html = md_to_html(md_path)

    print("2. Стилизация (тот же шаблон, что для миссий)...")
    html = inject_styles(html, args.header)

    print("3. Встраивание изображений как base64 (без локальных file:// ссылок)...")
    html = embed_images_as_base64(html, md_path.parent)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w",
                                      encoding="utf-8") as f:
        f.write(html)
        html_path = Path(f.name)

    print("4. HTML → PDF (Chrome headless)...")
    try:
        html_to_pdf(html_path, pdf_path)
        size_kb = pdf_path.stat().st_size / 1024
        print(f"\n  Готово: {pdf_path} ({size_kb:.0f} KB)")
        if size_kb < 400:
            print(f"  ⚠ ВНИМАНИЕ: PDF меньше 400 KB ({size_kb:.0f} KB) — возможно повреждён")
            return 2
    except subprocess.TimeoutExpired:
        print("ERROR: Chrome завис (>180 сек)")
        return 1
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors='replace')[:500] if e.stderr else 'unknown'
        print(f"ERROR: Chrome упал: {stderr}")
        return 1
    finally:
        if args.keep_html:
            html_copy = pdf_path.with_suffix(".html")
            html_path.rename(html_copy)
            print(f"  HTML:  {html_copy}")
        else:
            html_path.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
