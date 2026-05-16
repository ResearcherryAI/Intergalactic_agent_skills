#!/usr/bin/env python3
r"""
deliver_mission.py — выкатить готовый разбор миссии в личный кабинет клиента.

ОБЯЗАТЕЛЬНО перед запуском прочитай раздел «Что НЕ делать» в
deliver_mission.README.md. Было 3 инцидента, когда отправили разбор
на чужой email («из памяти» / по похожему имени) — теперь скрипт
блокирует такое поведение интерактивным подтверждением.

Принимает папку клиента вида `D:\DariaGalactic\Профайлы клиентов\<Имя_contract_дата>\`. Внутри ищет:
  • <что-то>_миссия.pdf      — полный разбор (загружается в Drive)
  • Generated_image.png      — обложка-визуализация (грузится в Drive в полном размере
                               и в R2 в виде сжатого WebP для кабинета)
  • summary.md               — выжимка по правилу _ПРАВИЛО_генерация_summary.md
                               (парсится в HTML и грузится в R2)

После загрузок дёргает Worker `/admin/mission`, который:
  • переводит миссию в статус `ready` (KV + Google Sheet),
  • отправляет клиенту письмо «Ваш разбор готов» (Resend),
  • отправляет WhatsApp «Анализ готов» через Green API, если в Sheet col P
    (Телефон) сохранён номер (по умолчанию — да, поле обязательное в формах).

У клиента в /me/ карточка миссии переходит в режим inline-preview:
обложка + три секции тезисов + кнопка «Скачать полный PDF».

Запуск:
    python3 deliver_mission.py [--yes] <email_клиента> <путь_к_папке_клиента>

Пример:
    python3 deliver_mission.py marianna@example.com \\
        "D:\\DariaGalactic\\Профайлы клиентов\\Марианна_on1778267701_20260508"

Флаги:
    --yes / -y   пропустить интерактивное подтверждение (только когда
                 оператор уже сверил email/имя в Sheet вручную; в норме —
                 НЕ ИСПОЛЬЗОВАТЬ).

Обратная совместимость: если вторым аргументом передан *.pdf, скрипт работает
по старой логике (только Drive + статус ready без inline-preview).

Конфиги (всё в DariaGalactic/config — папка в .gitignore):
  • client_secret_*.json — OAuth Desktop app из Google Cloud Console.
  • .env с WORKER_URL, ADMIN_SECRET, GDRIVE_FOLDER_ID.
  • gdrive_token.json создаётся автоматически после первой авторизации.

Установка зависимостей (один раз):
  python3 -m pip install --upgrade google-api-python-client google-auth-httplib2 \\
      google-auth-oauthlib requests python-dotenv Pillow markdown
"""

from __future__ import annotations

import io
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

SCRIPT_DIR = Path(__file__).resolve().parent
PRODUCTY_ROOT = Path(os.environ.get(
    'PRODUCTY_ROOT',
    str(Path.home() / 'Desktop' / 'Producty')
))
CONFIG_DIR = PRODUCTY_ROOT / 'DariaGalactic' / 'config'
DEFAULT_CLIENT_PROFILES_DIR = Path(os.environ.get(
    'CLIENT_PROFILES_DIR',
    os.environ.get('MISSION_LOCAL_DIR', r'D:\DariaGalactic\Профайлы клиентов'),
))

try:
    from dotenv import load_dotenv
    load_dotenv(CONFIG_DIR / '.env')
except ImportError:
    pass

# ── CONFIG ────────────────────────────────────────────────────────────
WORKER_URL = os.environ.get(
    'WORKER_URL',
    'https://intergalactic-cabinet.duduk12250405.workers.dev',
)
ADMIN_SECRET = os.environ.get('ADMIN_SECRET', '')
GDRIVE_FOLDER_ID = os.environ.get('GDRIVE_FOLDER_ID', '')

CF_ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '')
CF_R2_BUCKET = os.environ.get('CLOUDFLARE_R2_BUCKET', 'mission-content')

SCOPES = ['https://www.googleapis.com/auth/drive.file']
TOKEN_FILE = CONFIG_DIR / 'gdrive_token.json'

# Sheets API: используется для прямой записи в колонку O («Папка клиента
# в Drive») и для лукапа contractId/sheetRow по email. Токен лежит
# отдельно (`cabinet_sheet_token.json`) и имеет scope `spreadsheets`.
SHEETS_TOKEN_FILE = CONFIG_DIR / 'cabinet_sheet_token.json'
SHEETS_SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SHEET_ID = os.environ.get('SHEET_ID', '1X2voXTHnywDHXk1BRVNsYktrL8MtXHqxl6jhwymLzWE')
SHEET_TAB = os.environ.get('SHEET_TAB', 'Покупки')

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Цель сжатия обложки для кабинета: ширина 1200px, WebP качество 78.
COVER_TARGET_WIDTH = 1200
COVER_WEBP_QUALITY = 78


# ── Google Drive auth ────────────────────────────────────────────────
def find_client_secret() -> Path:
    candidates = sorted(CONFIG_DIR.glob('client_secret*.json'))
    if not candidates:
        sys.exit(
            f'client_secret_*.json не найден в {CONFIG_DIR}.\n'
            'Скопируйте OAuth client (Desktop app) JSON из Google Cloud Console туда.'
        )
    return candidates[0]


def get_drive_service():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(find_client_secret()), SCOPES)
            creds = flow.run_local_server(port=0, prompt='select_account')
        TOKEN_FILE.write_text(creds.to_json())
    return build('drive', 'v3', credentials=creds)


def get_sheets_service():
    """Sheets-сервис с отдельным токеном (scope spreadsheets)."""
    if not SHEETS_TOKEN_FILE.exists():
        return None
    import json as _json
    info = _json.loads(SHEETS_TOKEN_FILE.read_text())
    creds = Credentials.from_authorized_user_info(
        info, scopes=info.get('scopes') or SHEETS_SCOPES,
    )
    if not creds.valid:
        try:
            creds.refresh(Request())
        except Exception:
            return None
    return build('sheets', 'v4', credentials=creds)


# ── Helpers ───────────────────────────────────────────────────────────
def slugify_email(email: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', email.lower()).strip('_')


def safe_folder_segment(name: str) -> str:
    """Имя папки клиента в Drive: `<Имя>_<contract12>_<YYYYMMDD>`."""
    if not name:
        return 'client'
    # Убираем кавычки/слеши, схлопываем пробелы.
    cleaned = re.sub(r'[\\\/:*?"<>|]+', '', name).strip()
    cleaned = re.sub(r'\s+', '_', cleaned)
    return cleaned[:50] or 'client'


def short_contract(cid: str) -> str:
    if not cid:
        return 'unknown'
    return re.sub(r'[^A-Za-z0-9]+', '', cid)[-12:].lstrip('-') or 'unknown'


# ── Lookup клиента в Google Sheet ────────────────────────────────────
#
# contractId — ПЕРВИЧНЫЙ ключ. Извлекается из имени папки клиента
# (суффикс 12 hex-символов). Email — fallback, если contractId
# не найден или не передан.
#
# При нескольких строках на одном email без contractId:
# 1) строка без folderUrl (ещё не привязана), 2) самая свежая.

def _parse_all_mission_rows(sheets) -> list[dict]:
    """Читает Sheet один раз и возвращает все строки с продуктом «миссия»."""
    if not sheets:
        return []
    res = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f'{SHEET_TAB}!A1:P300',
    ).execute()
    rows = res.get('values', [])
    result = []
    for i, r in enumerate(rows[1:], start=2):
        cols = (r + [''] * 16)[:16]
        product = (cols[3] or '').lower()
        if 'миссия' not in product and 'миссии' not in product:
            continue
        result.append({
            'sheetRow': i,
            'datetime': cols[0],
            'email': cols[1],
            'buyerName': cols[2],
            'productName': cols[3],
            'amount': cols[4],
            'contractId': cols[5],
            'status': cols[6],
            'dateHuman': cols[7],
            'timeHuman': cols[8],
            'cityFull': cols[9],
            'coords': cols[10],
            'tzLabel': cols[11],
            'driveLink': cols[12],
            'deliveredAt': cols[13],
            'folderUrl': cols[14],
            'phone': cols[15],
        })
    return result


def extract_contract_from_folder(folder_name: str) -> str:
    """Извлекает 12-символьный contractId суффикс из имени папки."""
    m = re.search(r'_([0-9a-f]{12})_\d{8}$', folder_name)
    return m.group(1) if m else ''


def lookup_sheet_row_for_mission(sheets, email: str, contract_hint: str = '') -> dict | None:
    all_rows = _parse_all_mission_rows(sheets)
    if not all_rows:
        return None

    # 1) Первичный поиск: по contractId (суффикс 12 символов)
    if contract_hint:
        for r in all_rows:
            cid = (r['contractId'] or '').strip()
            if cid.endswith(contract_hint) or contract_hint in cid:
                return r

    # 2) Fallback: по email
    candidates = [r for r in all_rows
                  if (r['email'] or '').strip().lower() == email.strip().lower()]
    if not candidates:
        return None

    if len(candidates) > 1:
        print(f'   ⚠️  Найдено {len(candidates)} строк на email {email}:')
        for c in candidates:
            print(f'      row {c["sheetRow"]}: {c["buyerName"]} / {short_contract(c["contractId"])}')

    for c in candidates:
        if not c['folderUrl']:
            return c
    candidates.sort(key=lambda c: c['datetime'], reverse=True)
    return candidates[0]


def lookup_sheet_row_by_query(sheets, query: str) -> list[dict]:
    """Поиск по любому полю: имя, email, contractId, дата рождения."""
    all_rows = _parse_all_mission_rows(sheets)
    q = query.strip().lower()
    results = []
    for r in all_rows:
        searchable = '|'.join(str(v) for v in r.values()).lower()
        if q in searchable:
            results.append(r)
    return results


# ── Защита от инцидентов отправки (см. README раздел «Что НЕ делать»)
#
# Раньше были случаи, когда оператор отправлял разбор Алины на email
# Галины (потому что email брался «из памяти», а не из Sheet). Теперь
# скрипт обязательно показывает данные клиента из Sheet перед отправкой
# и требует подтверждения. Пропустить можно флагом --yes (только когда
# оператор гарантированно сверил — например, в скриптах автоматизации).
def confirm_client_dispatch(email: str, sheet_info: dict | None,
                            client_dir: Path, auto_yes: bool) -> None:
    print()
    print('━━━━━━━━━━━━━━━━ ПРОВЕРКА КЛИЕНТА ━━━━━━━━━━━━━━━━')
    print(f'  Email (передан скрипту) : {email}')
    if sheet_info:
        sheet_email = (sheet_info.get('email') or '').strip().lower()
        same = sheet_email == email.strip().lower()
        marker = '✓' if same else '✗'
        print(f'  Email (в Sheet, row {sheet_info["sheetRow"]:>3}): {sheet_email}  {marker}')
        print(f'  Имя клиента             : {sheet_info.get("buyerName") or "—"}')
        print(f'  Дата рождения           : {sheet_info.get("dateHuman") or "—"}')
        print(f'  Город                   : {sheet_info.get("cityFull") or "—"}')
        print(f'  contractId              : {sheet_info.get("contractId") or "—"}')
        print(f'  Телефон (col P)         : {sheet_info.get("phone") or "—"}')
        print(f'  Папка локально          : {client_dir.name}')
        folder_name_part = client_dir.name.split('_')[0].lower()
        sheet_name_part = (sheet_info.get('buyerName') or '').strip().lower()
        if sheet_name_part and folder_name_part and sheet_name_part != folder_name_part:
            print(f'  ⚠️  ВНИМАНИЕ: имя в Sheet ({sheet_info["buyerName"]}) ≠ имя в папке ({client_dir.name.split("_")[0]})')
        if not same:
            sys.exit(
                'СТОП: email в Sheet не совпадает с переданным аргументом. '
                'Это похоже на инцидент типа Алины/Марины. Проверь email '
                'руками в таблице и перезапусти скрипт.'
            )
    else:
        print(f'  Email (в Sheet)         : НЕ НАЙДЕН')
        print(f'  Папка локально          : {client_dir.name}')
        sys.exit(
            'СТОП: для этого email нет строки «Анализ миссии…» в Sheet. '
            'Возможные причины: 1) email написан с опечаткой, 2) клиент '
            'купил под другим адресом, 3) webhook от LavaTop не дошёл. '
            'Проверь руками в таблице и перезапусти скрипт. НЕ ОТПРАВЛЯЙ '
            'разбор «на тот email который помнишь» — было уже 3 инцидента '
            'когда так перепутали клиентов.'
        )
    print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    if auto_yes:
        print('  Подтверждено флагом --yes (без интерактива).')
        return
    try:
        ans = input('  Это правильный клиент? Отправить разбор? [yes/no] ').strip().lower()
    except EOFError:
        sys.exit('STDIN закрыт, а флага --yes нет. Отменено.')
    if ans not in ('y', 'yes', 'д', 'да'):
        sys.exit('Отменено оператором.')


def write_sheet_folder_url(sheets, sheet_row: int, folder_url: str) -> bool:
    """Прямая запись в Покупки!O<row>. True если ок."""
    if not sheets or not sheet_row:
        return False
    try:
        sheets.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=f'{SHEET_TAB}!O{sheet_row}',
            valueInputOption='USER_ENTERED',
            body={'values': [[folder_url]]},
        ).execute()
        return True
    except Exception as e:
        print(f'   ⚠️  Не удалось записать Sheet col O: {e}')
        return False


# ── Drive: subfolder клиента ─────────────────────────────────────────
#
# Структура: <GDRIVE_FOLDER_ID>/<safeName>_<contract12>_<YYYYMMDD>/
# Если у клиента нет contractId — fallback на email-slug и timestamp.
def find_or_create_client_folder(service, parent_id: str, name: str) -> dict:
    # В Drive query одинарные кавычки экранируются обратным слешем.
    safe_name = name.replace("'", "\\'")
    q = (
        f"name = '{safe_name}' and "
        f"'{parent_id}' in parents and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    res = service.files().list(q=q, fields='files(id,name,webViewLink)').execute()
    files = res.get('files', [])
    if files:
        f = files[0]
        # webViewLink не всегда возвращается — добиваем при необходимости.
        if not f.get('webViewLink'):
            f = service.files().get(fileId=f['id'], fields='id,name,webViewLink').execute()
        return f
    meta = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id],
    }
    f = service.files().create(body=meta, fields='id,name,webViewLink').execute()
    return f


def move_file_to_folder(service, file_id: str, new_parent: str) -> None:
    """Переносит уже залитый файл в нужную подпапку."""
    f = service.files().get(fileId=file_id, fields='parents').execute()
    prev = ','.join(f.get('parents') or [])
    service.files().update(
        fileId=file_id,
        addParents=new_parent,
        removeParents=prev,
        fields='id, parents',
    ).execute()


def file_id_from_link(link: str) -> str:
    """Достаёт fileId из webViewLink Drive (https://drive.google.com/file/d/<id>/view…)."""
    m = re.search(r'/d/([^/]+)/', link or '')
    return m.group(1) if m else ''


def find_pdf(client_dir: Path) -> Path | None:
    for cand in client_dir.glob('*_миссия.pdf'):
        return cand
    pdfs = sorted(client_dir.glob('*.pdf'))
    return pdfs[0] if pdfs else None


def find_cover_image(client_dir: Path) -> Path | None:
    for name in ('Generated_image.png', 'cover.png', 'cover.jpg', 'cover.jpeg'):
        p = client_dir / name
        if p.exists():
            return p
    pngs = sorted(client_dir.glob('*.png'))
    return pngs[0] if pngs else None


def find_summary(client_dir: Path) -> Path | None:
    p = client_dir / 'summary.md'
    return p if p.exists() else None


# ── Google Drive uploads ─────────────────────────────────────────────
def upload_to_drive(service, local_path: Path, remote_name: str, mimetype: str,
                    parent_folder_id: str | None = None) -> dict:
    """
    Загрузить файл в указанную папку Drive.
    Если parent_folder_id не задан — fallback на GDRIVE_FOLDER_ID (старое
    поведение). При наличии parent_folder_id (подпапка клиента) — кладём
    туда; ссылка по итогу публичная (anyone with link).
    """
    parent = parent_folder_id or GDRIVE_FOLDER_ID
    if not parent:
        sys.exit('Не задан parent для Drive (ни parent_folder_id, ни GDRIVE_FOLDER_ID в .env).')
    file_meta = {'name': remote_name, 'parents': [parent]}
    media = MediaFileUpload(str(local_path), mimetype=mimetype, resumable=True)
    f = service.files().create(
        body=file_meta, media_body=media, fields='id, name, webViewLink',
    ).execute()
    service.permissions().create(
        fileId=f['id'],
        body={'type': 'anyone', 'role': 'reader'},
        fields='id',
    ).execute()
    return f


# ── summary.md → HTML ────────────────────────────────────────────────
def parse_summary_md(md_path: Path) -> dict:
    """Возвращает {civilization, headline, cover, sections: [{title, items: [...]}]}."""
    text = md_path.read_text(encoding='utf-8')
    if not text.startswith('---'):
        sys.exit(f'{md_path}: отсутствует frontmatter (--- ... ---).')

    fm_end = text.find('\n---', 3)
    if fm_end == -1:
        sys.exit(f'{md_path}: не закрыт frontmatter блок.')
    fm = text[3:fm_end].strip()
    body = text[fm_end + 4:].strip()

    meta: dict = {}
    for line in fm.splitlines():
        line = line.strip()
        if not line or ':' not in line:
            continue
        key, val = line.split(':', 1)
        meta[key.strip()] = val.strip()

    for required in ('civilization', 'headline'):
        if not meta.get(required):
            sys.exit(f'{md_path}: в frontmatter нет поля "{required}".')

    sections: list[dict] = []
    current: dict | None = None
    for raw in body.splitlines():
        line = raw.rstrip()
        if line.startswith('## '):
            if current:
                sections.append(current)
            current = {'title': line[3:].strip(), 'items': []}
        elif line.startswith('- ') and current is not None:
            item = line[2:].strip()
            if item:
                current['items'].append(item)
    if current:
        sections.append(current)

    if len(sections) < 3:
        sys.exit(
            f'{md_path}: ожидаются 3 секции (Ваш дар / Ваш вызов / Что делать), '
            f'найдено {len(sections)}.'
        )
    for sec in sections:
        if not sec['items']:
            sys.exit(f'{md_path}: секция "{sec["title"]}" пустая.')

    return {
        'civilization': meta['civilization'],
        'headline': meta['headline'],
        'cover': meta.get('cover', 'Generated_image.png'),
        'sections': sections,
    }


SECTION_ICONS = {
    'дар': '✦',
    'вызов': '◯',
    'делать': '△',
    'практик': '△',
}


def section_icon(title: str) -> str:
    low = title.lower()
    for key, icon in SECTION_ICONS.items():
        if key in low:
            return icon
    return '•'


def html_escape(s: str) -> str:
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
             .replace('"', '&quot;').replace("'", '&#39;'))


def summary_to_html(parsed: dict) -> str:
    # NB: civilization и headline в HTML-фрагмент НЕ включаем, чтобы избежать
    # дубля в кабинете — клиентский me.js рендерит их из KV-payload отдельно.
    # Здесь только секции «Ваш дар / Ваш вызов / Что делать».
    parts = ['<div class="mi-summary">']
    for sec in parsed['sections']:
        icon = section_icon(sec['title'])
        parts.append('  <section class="mi-section">')
        parts.append(
            f'    <h3 class="mi-section-title"><span class="mi-section-icon">{icon}</span>'
            f'{html_escape(sec["title"])}</h3>'
        )
        parts.append('    <ul class="mi-list">')
        for item in sec['items']:
            parts.append(f'      <li>{html_escape(item)}</li>')
        parts.append('    </ul>')
        parts.append('  </section>')
    parts.append('</div>')
    return '\n'.join(parts)


# ── Cover image: PNG → WebP ──────────────────────────────────────────
def make_cover_webp(src_path: Path) -> bytes:
    try:
        from PIL import Image
    except ImportError:
        sys.exit('Pillow не установлен. Поставьте: pip install Pillow')

    img = Image.open(src_path)
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    if img.width > COVER_TARGET_WIDTH:
        ratio = COVER_TARGET_WIDTH / img.width
        new_size = (COVER_TARGET_WIDTH, int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format='WEBP', quality=COVER_WEBP_QUALITY, method=6)
    return buf.getvalue()


# ── R2 upload (через Worker /admin/r2/put) ───────────────────────────
def r2_put(key: str, body: bytes, content_type: str) -> None:
    if not ADMIN_SECRET:
        sys.exit('ADMIN_SECRET не задан в .env — невозможно загрузить в R2.')
    r = requests.post(
        WORKER_URL.rstrip('/') + '/admin/r2/put',
        headers={
            'X-Admin-Key': ADMIN_SECRET,
            'X-R2-Key': key,
            'X-R2-Content-Type': content_type,
        },
        data=body,
        timeout=60,
    )
    if r.status_code != 200:
        sys.exit(f'R2 PUT {key} — HTTP {r.status_code}: {r.text[:300]}')

def notify_worker(payload: dict) -> dict:
    if not ADMIN_SECRET:
        sys.exit('ADMIN_SECRET не задан в .env (получите у разработчика).')
    r = requests.post(
        WORKER_URL.rstrip('/') + '/admin/mission',
        headers={'X-Admin-Key': ADMIN_SECRET, 'Content-Type': 'application/json'},
        json=payload,
        timeout=20,
    )
    if r.status_code != 200:
        sys.exit(f'Worker ответил {r.status_code}: {r.text}')
    return r.json()


# ── Main flows ───────────────────────────────────────────────────────
def deliver_full(email: str, client_dir: Path, auto_yes: bool = False) -> None:
    pdf_path = find_pdf(client_dir)
    cover_path = find_cover_image(client_dir)
    summary_path = find_summary(client_dir)

    if not pdf_path:
        sys.exit(f'В {client_dir} не найден *_миссия.pdf')

    print(f'Email      : {email}')
    print(f'Папка      : {client_dir}')
    print(f'PDF        : {pdf_path.name}')
    print(f'Обложка    : {cover_path.name if cover_path else "—"}')
    print(f'Summary    : {"есть" if summary_path else "нет"}')
    print(f'Worker     : {WORKER_URL}')
    print()

    service = get_drive_service()
    sheets = get_sheets_service()
    slug = slugify_email(email)
    ts = datetime.now().strftime('%Y-%m-%d_%H-%M')

    contract_hint = extract_contract_from_folder(client_dir.name)
    sheet_info = lookup_sheet_row_for_mission(sheets, email, contract_hint=contract_hint)

    # CRITICAL: показать оператору данные клиента и заставить подтвердить.
    # Без этого блока было 3 инцидента «отправили не тому клиенту».
    confirm_client_dispatch(email, sheet_info, client_dir, auto_yes)

    contract_id = (sheet_info or {}).get('contractId') or ''
    sheet_row = (sheet_info or {}).get('sheetRow') or 0
    buyer_name = (sheet_info or {}).get('buyerName') or ''
    purchased_at = (sheet_info or {}).get('datetime') or ''
    print(f'   Sheet match: row {sheet_row}  contractId={contract_id or "—"}  buyer={buyer_name}')

    # Папка клиента на Drive: <Имя>_<contract12>_<YYYYMMDD>.
    folder_url = (sheet_info or {}).get('folderUrl') or ''
    folder_id = ''
    if GDRIVE_FOLDER_ID:
        try:
            date_for_name = ''
            if purchased_at:
                # Sheet col A — формат «YYYY-MM-DD HH:MM».
                m = re.match(r'(\d{4})-(\d{2})-(\d{2})', purchased_at)
                if m:
                    date_for_name = f'{m.group(1)}{m.group(2)}{m.group(3)}'
            if not date_for_name:
                date_for_name = datetime.now().strftime('%Y%m%d')
            folder_name = f'{safe_folder_segment(buyer_name or slug)}_{short_contract(contract_id)}_{date_for_name}'
            print(f'1) Готовлю папку клиента в Drive: {folder_name}')
            folder = find_or_create_client_folder(service, GDRIVE_FOLDER_ID, folder_name)
            folder_id = folder['id']
            folder_url = folder.get('webViewLink') or f'https://drive.google.com/drive/folders/{folder_id}'
            print(f'   OK: {folder_url}')
        except Exception as e:
            print(f'   ⚠️  Не удалось создать папку клиента ({e}). Файлы пойдут в общую папку.')
            folder_id = ''

    print('2) Загружаю PDF…')
    pdf_remote = f'mission_{slug}_{ts}.pdf'
    pdf_file = upload_to_drive(service, pdf_path, pdf_remote, 'application/pdf', folder_id or None)
    drive_link = pdf_file.get('webViewLink', '')
    print(f'   OK: {pdf_file["name"]}')

    drive_image_link = ''
    if cover_path:
        print('3) Загружаю полную обложку (PNG)…')
        png_remote = f'mission_{slug}_{ts}_cover.png'
        png_file = upload_to_drive(service, cover_path, png_remote, 'image/png', folder_id or None)
        drive_image_link = png_file.get('webViewLink', '')
        print(f'   OK: {png_file["name"]}')

    # Записываем ссылку на папку клиента прямо в Sheet col O (даже без
    # деплоя нового /admin/mission/drive endpoint — это даёт Дарье
    # моментальную ссылку из таблицы).
    if folder_id and folder_url and sheet_row:
        if write_sheet_folder_url(sheets, sheet_row, folder_url):
            print(f'   ✓ Sheet col O (row {sheet_row}) ← {folder_url}')

    payload = {
        'email': email,
        'status': 'ready',
        'driveLink': drive_link,
        'fileName': pdf_file['name'],
        'driveImageLink': drive_image_link,
    }
    if contract_id:
        payload['contractId'] = contract_id

    if summary_path and cover_path:
        print('4) Парсю summary.md и собираю HTML…')
        parsed = parse_summary_md(summary_path)
        html = summary_to_html(parsed)
        print(f'   OK: civilization={parsed["civilization"]}, секций={len(parsed["sections"])}')

        print('5) Сжимаю обложку в WebP для кабинета…')
        cover_bytes = make_cover_webp(cover_path)
        print(f'   OK: {len(cover_bytes) // 1024} KB')

        # R2-ключи делим по contractId (если есть), иначе по slug-email.
        # contractId надёжнее — выдерживает несколько миссий на одном email.
        r2_partition = short_contract(contract_id) if contract_id else slug
        print(f'6) Загружаю cover.webp и summary.html в Cloudflare R2 (partition={r2_partition})…')
        cover_key = f'mission/{r2_partition}/cover.webp'
        summary_key = f'mission/{r2_partition}/summary.html'
        r2_put(cover_key, cover_bytes, 'image/webp')
        r2_put(summary_key, html.encode('utf-8'), 'text/html; charset=utf-8')
        print(f'   OK: {cover_key}, {summary_key}')

        payload.update({
            'inlinePreview': True,
            'coverKey': cover_key,
            'summaryKey': summary_key,
            'civilization': parsed['civilization'],
            'headline': parsed['headline'],
        })
    else:
        print('4) summary.md или обложка отсутствуют — кабинет покажет старую кнопку «Открыть разбор».')

    print('7) Обновляю личный кабинет (Worker /admin/mission)…')
    res = notify_worker(payload)
    print(f'   OK: статус миссии для {email} → ready (inline-preview: '
          f'{"да" if payload.get("inlinePreview") else "нет"})')
    if res.get('sheetError'):
        print(f'   ⚠️  Sheet update warning: {res["sheetError"]}')

    # Письмо «разбор готов» — воркер отправляет автоматически в тот
    # момент, когда статус миссии перешёл в ready (т.е. при первой
    # выкатке). При повторной выкатке (переаплоад PDF) письмо НЕ
    # дублируется. Чтобы принудительно отправить ещё раз, передать
    # в payload {"notifyEmail": true}.
    if res.get('emailSent'):
        print('   ✓ Письмо «разбор готов» отправлено клиенту.')
    elif res.get('emailError'):
        print(f'   ⚠️  Письмо не отправлено: {res["emailError"]}')
    elif res.get('previousStatus') == 'ready':
        print('   = Письмо не отправлено: миссия уже была в статусе ready '
              '(повторная выкатка).')
    else:
        print('   = Письмо не отправлено: не было перехода в ready.')

    # WhatsApp клиенту. Воркер с версии wa-greenapi-v3 шлёт WA-уведомление
    # «Анализ миссии звёздной души готов», если в mission.phone сохранён
    # номер. Если phone нет в KV (старые клиенты без поля) — WA пропускается.
    if res.get('waSent') is True:
        print('   ✓ WhatsApp «разбор готов» отправлено клиенту.')
    elif res.get('waReason'):
        print(f'   ⚠️  WhatsApp не отправлен: {res["waReason"]}')
    elif sheet_info and not (sheet_info.get('phone')):
        print('   = WhatsApp не отправлен: в Sheet col P (Телефон) пусто.')


def deliver_legacy_pdf(email: str, pdf_path: Path) -> None:
    """Старый режим — только PDF без R2."""
    print(f'Email   : {email}')
    print(f'PDF     : {pdf_path}')
    print(f'Worker  : {WORKER_URL}')
    print('(legacy режим — без обложки и без summary)')
    print()

    service = get_drive_service()
    slug = slugify_email(email)
    ts = datetime.now().strftime('%Y-%m-%d_%H-%M')
    pdf_remote = f'mission_{slug}_{ts}.pdf'

    print('1) Загружаю PDF на Google Drive…')
    pdf_file = upload_to_drive(service, pdf_path, pdf_remote, 'application/pdf')
    drive_link = pdf_file.get('webViewLink', '')
    print(f'   OK: {pdf_file["name"]}')

    print('2) Обновляю личный кабинет…')
    res = notify_worker({
        'email': email, 'status': 'ready',
        'driveLink': drive_link, 'fileName': pdf_file['name'],
    })
    print(f'   OK: статус миссии для {email} → ready')
    if res.get('emailSent'):
        print('   ✓ Письмо «разбор готов» отправлено клиенту.')
    elif res.get('emailError'):
        print(f'   ⚠️  Письмо не отправлено: {res["emailError"]}')
    elif res.get('previousStatus') == 'ready':
        print('   = Письмо не отправлено: миссия уже была в статусе ready.')


def run_lookup(query: str) -> None:
    """Поиск клиента в Sheet по любому полю."""
    sheets = get_sheets_service()
    results = lookup_sheet_row_by_query(sheets, query)
    if not results:
        print(f'Ничего не найдено по запросу: {query}')
        return
    print(f'Найдено {len(results)} строк:\n')
    for r in results:
        cid_short = short_contract(r['contractId'])
        print(f'  Row {r["sheetRow"]}: {r["buyerName"]} | {r["email"]} | '
              f'{r["dateHuman"]} | {r["cityFull"]} | {cid_short} | {r["status"]}')


def main():
    args = [a for a in sys.argv[1:] if a]
    auto_yes = False
    if '--yes' in args:
        auto_yes = True
        args.remove('--yes')
    if '-y' in args:
        auto_yes = True
        args.remove('-y')
    if '--lookup' in args:
        args.remove('--lookup')
        run_lookup(' '.join(args) if args else '')
        return
    if len(args) < 2:
        print(__doc__)
        print('Использование:')
        print('  deliver_mission.py [--yes] <email> <папка_или_pdf>')
        print('  deliver_mission.py --lookup <запрос>')
        sys.exit(2)
    email = args[0].strip().lower()
    target_arg = Path(args[1]).expanduser()
    target = (
        target_arg.resolve()
        if target_arg.is_absolute()
        else (DEFAULT_CLIENT_PROFILES_DIR / target_arg).resolve()
    )

    if not EMAIL_RE.match(email):
        sys.exit(f'Email "{email}" выглядит некорректно.')
    if not target.exists():
        sys.exit(f'Путь {target} не найден.')

    if target.is_file() and target.suffix.lower() == '.pdf':
        # Legacy-режим тоже проверяет email, но мягче (нет папки клиента
        # для дополнительной сверки). Подтверждение всё равно требуется.
        sheets = get_sheets_service()
        sheet_info = lookup_sheet_row_for_mission(sheets, email)
        confirm_client_dispatch(email, sheet_info, target.parent, auto_yes)
        deliver_legacy_pdf(email, target)
    elif target.is_dir():
        deliver_full(email, target, auto_yes=auto_yes)
    else:
        sys.exit('Передайте папку клиента или путь к *.pdf.')

    print()
    print('Готово.')


if __name__ == '__main__':
    main()
