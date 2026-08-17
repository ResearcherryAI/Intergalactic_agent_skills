#!/usr/bin/env python3
"""
generate_pdf.py — генерация стильного PDF из Markdown-разбора миссии.

Стек: Markdown → pandoc → HTML5 → Chrome headless → PDF.

Запуск:
    python3 generate_pdf.py -i "Марианна_11011989_20260508/Марианна_11011989_миссия.md"
    python3 generate_pdf.py -i some_file.md -o custom_name.pdf
    python3 generate_pdf.py --help
"""
from __future__ import annotations

import argparse
import base64
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

PROFILES_DIR = Path(os.environ.get(
    "CLIENT_PROFILES_DIR",
    os.environ.get("MISSION_LOCAL_DIR", r"D:\DariaGalactic\Профайлы клиентов"),
))


def _resolve_pandoc() -> str:
    override = os.environ.get("PANDOC_EXECUTABLE")
    if override:
        return override
    if platform.system() == "Darwin":
        brew = Path("/opt/homebrew/bin/pandoc")
        if brew.is_file():
            return str(brew)
    found = shutil.which("pandoc")
    if not found:
        raise FileNotFoundError(
            "pandoc не найден. Установите Pandoc или задайте переменную PANDOC_EXECUTABLE"
        )
    return found


def _resolve_chrome() -> str:
    override = os.environ.get("CHROME_EXECUTABLE")
    if override:
        return override
    if platform.system() == "Darwin":
        p = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if p.is_file():
            return str(p)
    elif platform.system() == "Windows":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        la = os.environ.get("LOCALAPPDATA", "")
        for cand in (
            Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(pf86) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(la) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ):
            if cand.is_file():
                return str(cand)
        for exe in shutil.which("chrome"), shutil.which("chrome.exe"):
            if exe:
                return exe
    else:
        for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
            found = shutil.which(name)
            if found:
                return found
    raise FileNotFoundError(
        "Google Chrome не найден. Установите Chrome или задайте CHROME_EXECUTABLE"
    )


PANDOC = _resolve_pandoc()
CHROME = _resolve_chrome()


def embed_images_as_base64(html: str, base_dir: Path) -> str:
    def replace_img(m):
        tag_before, src, tag_after = m.group(1), m.group(2), m.group(3)
        p = base_dir / src if not Path(src).is_absolute() else Path(src)
        if p.exists() and p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.svg'):
            mime = {'.png': 'image/png', '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg', '.gif': 'image/gif',
                    '.svg': 'image/svg+xml'}.get(p.suffix.lower(), 'image/png')
            b64 = base64.b64encode(p.read_bytes()).decode()
            return f'{tag_before}data:{mime};base64,{b64}{tag_after}'
        return m.group(0)
    return re.sub(r'(<img[^>]*\ssrc=["\'])([^"\']+)(["\'][^>]*>)', replace_img, html)


def md_to_html(md_path: Path) -> str:
    result = subprocess.run(
        [PANDOC, str(md_path),
         "-f", "markdown+emoji",
         "-t", "html5",
         "--standalone",
         "--css", os.devnull],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    html = result.stdout or ""
    html = re.sub(r'<header id="title-block-header">.*?</header>', '', html, flags=re.DOTALL)
    return html


def split_service_client(html: str) -> str:
    """Обернуть блок СЛУЖЕБНЫЙ БЛОК в div.service, КЛИЕНТСКИЙ ТЕКСТ в div.client."""
    html = re.sub(
        r'(<h2[^>]*id="[^"]*структура-днк[^"]*"[^>]*>[^<]*</h2>)',
        r'<div class="service-block">\1',
        html, count=1, flags=re.IGNORECASE
    )
    html = re.sub(
        r'(<h2[^>]*id="[^"]*анализ-миссии[^"]*"[^>]*>[^<]*</h2>)',
        r'</div><!-- /service-block -->\n<div class="client-block">\1',
        html, count=1, flags=re.IGNORECASE
    )
    if '<div class="client-block">' in html:
        html = html.replace('</body>', '</div><!-- /client-block -->\n</body>')
    return html


def inject_styles(html: str, header_text: str) -> str:
    css = f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;0,700;1,400&family=Inter:wght@400;500;600;700&display=swap');

    :root {{
        --gold: #c9a86a;
        --gold-light: #f0d8a0;
        --navy: #0a0815;
        --navy-mid: #161229;
        --navy-light: #1e1a35;
        --text-main: #2a2540;
        --text-light: #6d6880;
        --text-warm: #4a3f5e;
        --accent-blue: #7b8db8;
        --accent-rose: #b88a8a;
        --bg-cream: #faf8f4;
        --bg-warm: #f5f0e8;
        --border-soft: #e8e0d0;
    }}

    @page {{
        size: A4;
        margin: 18mm 16mm 20mm 16mm;
        @top-center {{
            content: "{header_text}";
            font-family: 'Inter', sans-serif;
            font-size: 7pt;
            color: #b0a890;
            letter-spacing: 0.3px;
        }}
        @bottom-center {{
            content: counter(page);
            font-family: 'Inter', sans-serif;
            font-size: 7.5pt;
            color: #b0a890;
        }}
    }}

    body {{
        font-family: 'Inter', 'DejaVu Sans', sans-serif;
        font-size: 10pt;
        line-height: 1.6;
        color: var(--text-main);
        max-width: 210mm;
        margin: 0 auto;
        padding: 0;
        background: #fff;
    }}

    /* ═══════════════ ЗАГОЛОВКИ ═══════════════ */

    h1 {{
        font-family: 'Cormorant Garamond', Georgia, serif;
        font-size: 22pt;
        font-weight: 700;
        color: var(--navy);
        text-align: center;
        margin: 0 0 6px 0;
        padding: 24px 20px 12px;
        letter-spacing: 0.5px;
        line-height: 1.3;
        page-break-after: avoid;
    }}
    h1::after {{
        content: '';
        display: block;
        width: 60px;
        height: 2px;
        background: linear-gradient(90deg, transparent, var(--gold), transparent);
        margin: 12px auto 0;
    }}

    h2 {{
        font-family: 'Cormorant Garamond', Georgia, serif;
        font-size: 13pt;
        font-weight: 600;
        color: var(--navy-mid);
        text-transform: uppercase;
        letter-spacing: 2px;
        text-align: center;
        margin: 28px 0 16px;
        padding: 10px 0;
        border-top: 1px solid var(--border-soft);
        border-bottom: 1px solid var(--border-soft);
        page-break-after: avoid;
    }}

    h3 {{
        font-family: 'Cormorant Garamond', Georgia, serif;
        font-size: 14pt;
        font-weight: 700;
        color: var(--navy);
        margin: 22px 0 8px;
        padding-bottom: 4px;
        border-bottom: 1.5px solid var(--gold);
        page-break-after: avoid;
        text-align: left;
    }}

    h4 {{
        font-family: 'Inter', sans-serif;
        font-size: 10pt;
        font-weight: 600;
        color: var(--text-warm);
        margin: 14px 0 4px;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        page-break-after: avoid;
        text-align: left;
    }}

    /* ═══════════════ ТЕКСТ ═══════════════ */

    p {{
        margin: 6px 0;
        text-align: justify;
        hyphens: auto;
    }}

    strong {{
        font-weight: 700;
        color: var(--navy);
    }}

    em {{
        color: var(--text-warm);
    }}

    /* ═══════════════ БЛОК-ЦИТАТА (дисклеймер) ═══════════════ */

    blockquote {{
        background: linear-gradient(135deg, var(--bg-warm) 0%, #f8f4ec 100%);
        border-left: 3px solid var(--gold);
        border-radius: 0 8px 8px 0;
        padding: 14px 18px;
        margin: 16px 0;
        font-style: italic;
        color: var(--text-warm);
        font-size: 9.5pt;
        line-height: 1.6;
        page-break-inside: avoid;
    }}
    blockquote p {{
        margin: 4px 0;
    }}

    /* ═══════════════ ТАБЛИЦЫ ═══════════════ */

    table {{
        border-collapse: collapse;
        width: 100%;
        margin: 12px 0;
        font-size: 8.5pt;
        page-break-inside: avoid;
        border: 1px solid var(--border-soft);
        border-radius: 6px;
    }}
    th {{
        background: var(--navy);
        color: var(--gold-light);
        font-weight: 600;
        padding: 8px 10px;
        text-align: left;
        font-size: 8pt;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    td {{
        border-bottom: 1px solid var(--border-soft);
        padding: 7px 10px;
        text-align: left;
        vertical-align: top;
        color: var(--text-main);
    }}
    tr:nth-child(even) {{
        background: var(--bg-cream);
    }}
    tr:last-child td {{
        border-bottom: none;
    }}

    /* широкая таблица препятствий */
    table:has(th:nth-child(5)) {{
        font-size: 7.5pt;
    }}
    table:has(th:nth-child(5)) th,
    table:has(th:nth-child(5)) td {{
        padding: 5px 6px;
    }}

    /* ═══════════════ СПИСКИ ═══════════════ */

    ul, ol {{
        padding-left: 22px;
        margin: 6px 0;
    }}
    li {{
        margin: 4px 0;
        line-height: 1.55;
    }}
    li strong {{
        color: var(--navy);
    }}

    /* ═══════════════ ГОРИЗОНТАЛЬНЫЕ ЛИНИИ ═══════════════ */

    hr {{
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent 5%, var(--border-soft) 30%, var(--gold) 50%, var(--border-soft) 70%, transparent 95%);
        margin: 20px 0;
        page-break-after: avoid;
    }}

    /* ═══════════════ CTA-СТРЕЛКИ ═══════════════ */

    p:has(> em:only-child) {{
        background: linear-gradient(135deg, #f8f4ec, #faf8f4);
        border-left: 3px solid var(--accent-blue);
        padding: 10px 14px;
        border-radius: 0 6px 6px 0;
        margin: 12px 0;
        font-size: 9pt;
    }}

    /* ═══════════════ СЛУЖЕБНЫЙ БЛОК ═══════════════ */

    .service-block {{
        background: var(--bg-cream);
        border: 1px solid var(--border-soft);
        border-radius: 8px;
        padding: 8px 16px;
        margin: 12px 0;
        font-size: 8.5pt;
        line-height: 1.45;
        color: var(--text-light);
    }}
    .service-block h2 {{
        font-size: 10pt;
        color: var(--text-light);
        letter-spacing: 1.5px;
        margin: 8px 0 10px;
        border-color: var(--border-soft);
    }}
    .service-block h3 {{
        font-size: 9.5pt;
        color: var(--text-light);
        border-bottom-color: var(--border-soft);
        margin: 10px 0 4px;
    }}
    .service-block table {{
        font-size: 7.5pt;
    }}
    .service-block th {{
        background: #4a4560;
        font-size: 7pt;
    }}

    /* ═══════════════ КЛИЕНТСКИЙ БЛОК ═══════════════ */

    .client-block h2 {{
        page-break-before: always;
    }}
    .client-block h2:first-child {{
        page-break-before: avoid;
    }}

    /* ═══════════════ ИЗОБРАЖЕНИЯ ═══════════════ */

    img {{
        max-width: 90%;
        height: auto;
        display: block;
        margin: 16px auto;
        page-break-inside: avoid;
        border-radius: 6px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}

    /* ═══════════════ ССЫЛКИ ═══════════════ */

    a {{ color: var(--accent-blue); text-decoration: none; }}

    /* ═══════════════ КОД ═══════════════ */

    code {{
        background: var(--bg-cream);
        padding: 1px 4px;
        border-radius: 3px;
        font-size: 8.5pt;
        color: var(--text-warm);
    }}

    /* ═══════════════ СТРАНИЦА РАЗРЫВОВ ═══════════════ */

    h2 + table, h3 + table {{ page-break-before: avoid; }}
    h3 + blockquote {{ page-break-before: avoid; }}
    h3 + ul, h3 + ol {{ page-break-before: avoid; }}

    /* первый h1 без разрыва */
    h1:first-of-type {{ page-break-before: avoid; }}
    </style>
    """
    html = re.sub(
        r"<link\s+[^>]*rel=[\"']stylesheet[\"'][^>]*>[ \t]*\n?",
        "",
        html,
        flags=re.I,
    )
    return html.replace("</head>", css + "\n</head>")


def html_to_pdf(html_path: Path, pdf_path: Path):
    subprocess.run(
        [CHROME,
         "--headless",
         "--disable-gpu",
         "--no-sandbox",
         f"--print-to-pdf={pdf_path}",
         "--run-all-compositor-stages-before-draw",
         "--virtual-time-budget=15000",
         str(html_path)],
        capture_output=True, check=True, timeout=180
    )


def main():
    parser = argparse.ArgumentParser(
        description="Генерация стильного PDF из Markdown-разбора миссии"
    )
    parser.add_argument("--input", "-i", type=Path, required=True,
                        help="Markdown-файл разбора")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="PDF (по умолчанию — рядом с .md)")
    parser.add_argument("--header", type=str,
                        default="intergalactic-astrology.com  ·  Kaya Kaen  ·  Разбор миссии",
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

    print("2. Разделение служебного и клиентского блоков...")
    html = split_service_client(html)

    print("3. Стилизация (космическая палитра, типографика)...")
    html = inject_styles(html, args.header)

    print("4. Встраивание изображений...")
    html = embed_images_as_base64(html, md_path.parent)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w",
                                      encoding="utf-8") as f:
        f.write(html)
        html_path = Path(f.name)

    print("5. HTML → PDF (Chrome headless)...")
    try:
        html_to_pdf(html_path, pdf_path)
        size_kb = pdf_path.stat().st_size / 1024
        print(f"\n  Готово: {pdf_path} ({size_kb:.0f} KB)")
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
