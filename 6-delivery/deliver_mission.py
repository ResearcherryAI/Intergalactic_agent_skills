#!/usr/bin/env python3
"""
deliver_mission.py — выкатить готовый разбор миссии или Архитектуры денег
в личный кабинет клиента.

ОБЯЗАТЕЛЬНО перед запуском прочитай раздел «Что НЕ делать» в
deliver_mission.README.md. Было 3 инцидента, когда отправили разбор
на чужой email («из памяти» / по похожему имени) — теперь скрипт
блокирует такое поведение интерактивным подтверждением.

Принимает папку клиента вида `Профайлы клиентов/<Имя_contract_дата>/`. Внутри ищет:
  • <что-то>_миссия.pdf       — для --product mission
  • <что-то>_деньги.pdf       — для --product money_dna
  • Generated_image.png       — обложка-визуализация (грузится в Drive в полном размере
                                и в R2 в виде сжатого WebP для кабинета)
  • summary.md                — выжимка по правилу _ПРАВИЛО_генерация_summary.md
                                (парсится в HTML и грузится в R2)

После загрузок дёргает Worker `/admin/mission`, который:
  • переводит запись в статус `ready` (KV + Google Sheet) по contractId,
  • отправляет клиенту письмо «Ваш разбор готов» (Resend),
  • отправляет WhatsApp «Анализ готов» через Green API, если в Sheet col P
    (Телефон) сохранён номер (по умолчанию — да, поле обязательное в формах).

У клиента в /me/ карточка переходит в режим inline-preview:
обложка + три секции тезисов + кнопка «Скачать полный PDF».

Запуск:
    python3 deliver_mission.py --product mission|money_dna [--yes] \\
        <email_клиента> <путь_к_папке_клиента>

Пример (миссия):
    python3 deliver_mission.py --product mission --yes marianna@example.com \\
        "/Users/kirill/.../Профайлы клиентов/Марианна_on1778267701_20260508"

Пример (деньги):
    python3 deliver_mission.py --product money_dna --yes natalya@example.com \\
        "/Users/kirill/.../Профайлы клиентов/Наталья_xx_20260523"

Флаги:
    --product   ОБЯЗАТЕЛЬНЫЙ. mission или money_dna. Значение брать из
                колонки D Sheet:
                  «Анализ миссии звёздной души» → mission
                  «Архитектура Денег — код 50.56» → money_dna
    --yes / -y  пропустить интерактивное подтверждение (только когда
                оператор уже сверил email/имя в Sheet вручную; в норме —
                НЕ ИСПОЛЬЗОВАТЬ).

Обратная совместимость: если вторым аргументом передан *.pdf, скрипт работает
по старой логике (только Drive + статус ready без inline-preview).

Конфиги (всё в DariaGalactic/config — папка в .gitignore):
  • client_secret_*.json — OAuth Desktop app из Google Cloud Console.
  • .env с WORKER_URL, ADMIN_SECRET, GDRIVE_FOLDER_ID,
    CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_R2_BUCKET, CLOUDFLARE_R2_TOKEN.
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
AGENT_DIR = SCRIPT_DIR.parent  # intergalacticAstoAgent/
_producty_root = Path(os.environ.get('PRODUCTY_ROOT', AGENT_DIR.parent))
CONFIG_DIR = _producty_root / 'DariaGalactic' / 'config'
if not CONFIG_DIR.exists():
    CONFIG_DIR = AGENT_DIR / 'DariaGalactic' / 'config'

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
CF_R2_TOKEN = os.environ.get('CLOUDFLARE_R2_TOKEN', '')

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


# ── Lookup клиента в Google Sheet по email ──────────────────────────
#
# Возвращает {sheetRow, contractId, buyerName, dateHuman, purchasedAt,
# folderUrl, phone} либо None. Для миссий, у которых в Sheet 2+ строк (на
# одном email несколько контрактов), берёт первую с непустым D
# («Анализ миссии…») и пустым O («Папка клиента») — то есть ту, для
# которой папка ещё не привязана. Если все привязаны — берёт самую
# свежую по A-колонке (timestamp).
def lookup_sheet_row_for_mission(sheets, email: str, contract_hint: str = '',
                                 product_code: str = 'mission') -> dict | None:
    """FIX-28: фильтруем строки Sheet по `productCode`.
       mission → строки с D содержащим «миссия/миссии»;
       money_dna → строки с D содержащим «архитектур»/«50.56»/«денег».
    """
    if not sheets:
        return None
    if product_code == 'money_dna':
        product_keywords = ('архитектур', 'денег', '50.56')
    else:
        product_keywords = ('миссия', 'миссии')

    # P = Телефон (WhatsApp). Range расширен до A:P, чтобы вытянуть phone.
    res = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f'{SHEET_TAB}!A1:P300',
    ).execute()
    rows = res.get('values', [])
    candidates = []
    for i, r in enumerate(rows[1:], start=2):  # skip header (row 1)
        cols = (r + [''] * 16)[:16]
        if (cols[1] or '').strip().lower() != email.strip().lower():
            continue
        product_cell = (cols[3] or '').lower()
        if not any(k in product_cell for k in product_keywords):
            continue
        candidates.append({
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
    if not candidates:
        return None
    if contract_hint:
        for c in candidates:
            if (c['contractId'] or '').strip() == contract_hint.strip():
                return c
    # 1) сначала строка без folderUrl
    for c in candidates:
        if not c['folderUrl']:
            return c
    # 2) иначе — самая свежая по datetime (col A)
    candidates.sort(key=lambda c: c['datetime'], reverse=True)
    return candidates[0]


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


def find_pdf(client_dir: Path, product_code: str = 'mission') -> Path | None:
    """FIX-28: ищем PDF по продукту. mission → *_миссия.pdf, money_dna → *_деньги.pdf.
    Fallback на *.pdf оставлен как safety net, но с предупреждением — это
    защита от опечатки в имени файла, не штатный путь.
    """
    suffix = '*_деньги.pdf' if product_code == 'money_dna' else '*_миссия.pdf'
    for cand in client_dir.glob(suffix):
        return cand
    pdfs = sorted(client_dir.glob('*.pdf'))
    if pdfs:
        print(f'   ⚠️  Не найден {suffix}, использую {pdfs[0].name} (проверь, что это правильный файл).')
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


# ── R2 upload ────────────────────────────────────────────────────────
def r2_put_via_worker(key: str, body: bytes, content_type: str) -> None:
    """Fallback: PUT через worker endpoint /admin/r2/put.
    Используется когда CLOUDFLARE_R2_TOKEN не задан или не имеет
    R2 Object Write permissions (типичный случай — токен сделан только
    под Workers Edit). У воркера биндинг MISSION_R2 уже работает.
    """
    if not ADMIN_SECRET:
        sys.exit('Нет CLOUDFLARE_R2_TOKEN и нет ADMIN_SECRET — некуда лить cover/summary в R2.')
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
        sys.exit(f'R2 PUT (worker) {key} → HTTP {r.status_code}: {r.text[:300]}')


def r2_put(key: str, body: bytes, content_type: str) -> None:
    # Сначала пытаемся через прямой CF API (быстрее и без worker hop).
    # Если токен отсутствует или у него нет прав — падаем в worker
    # endpoint, который работает по ADMIN_SECRET.
    if CF_ACCOUNT_ID and CF_R2_TOKEN and CF_R2_BUCKET:
        url = (
            f'https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}'
            f'/r2/buckets/{CF_R2_BUCKET}/objects/{key}'
        )
        r = requests.put(
            url,
            headers={
                'Authorization': f'Bearer {CF_R2_TOKEN}',
                'Content-Type': content_type,
            },
            data=body,
            timeout=60,
        )
        if r.status_code == 200:
            return
        # 401/403 — у токена нет R2 Object Write, идём в fallback.
        if r.status_code in (401, 403):
            print(f'   ⚠️  CF R2 API вернул {r.status_code}, переключаюсь на worker /admin/r2/put.')
            r2_put_via_worker(key, body, content_type)
            return
        sys.exit(f'R2 PUT {key} → HTTP {r.status_code}: {r.text[:300]}')
    # Нет токена — сразу через воркер.
    r2_put_via_worker(key, body, content_type)


# ── Worker notify ────────────────────────────────────────────────────
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
def deliver_full(email: str, client_dir: Path, auto_yes: bool = False,
                 product_code: str = 'mission') -> None:
    # FIX-28: префикс файлов и R2-ключей зависит от продукта.
    # mission → mission_<slug>_<ts>.pdf, R2 mission/<contract>/...
    # money_dna → money_dna_<slug>_<ts>.pdf, R2 money_dna/<contract>/...
    prefix = 'money_dna' if product_code == 'money_dna' else 'mission'
    expected_suffix = '*_деньги.pdf' if product_code == 'money_dna' else '*_миссия.pdf'

    pdf_path = find_pdf(client_dir, product_code)
    cover_path = find_cover_image(client_dir)
    summary_path = find_summary(client_dir)

    if not pdf_path:
        sys.exit(f'В {client_dir} не найден {expected_suffix}')

    print(f'Product    : {product_code}')
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

    # Лукап в Sheet — нужен contractId, sheetRow и dateHuman, чтобы
    # привязать аплоад к правильной строке и собрать имя папки клиента.
    # FIX-28: продукт-фильтр (mission | money_dna).
    sheet_info = lookup_sheet_row_for_mission(sheets, email, product_code=product_code)

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
    pdf_remote = f'{prefix}_{slug}_{ts}.pdf'
    pdf_file = upload_to_drive(service, pdf_path, pdf_remote, 'application/pdf', folder_id or None)
    drive_link = pdf_file.get('webViewLink', '')
    print(f'   OK: {pdf_file["name"]}')

    drive_image_link = ''
    if cover_path:
        print('3) Загружаю полную обложку (PNG)…')
        png_remote = f'{prefix}_{slug}_{ts}_cover.png'
        png_file = upload_to_drive(service, cover_path, png_remote, 'image/png', folder_id or None)
        drive_image_link = png_file.get('webViewLink', '')
        print(f'   OK: {png_file["name"]}')

    # Записываем ссылку на папку клиента прямо в Sheet col O (даже без
    # деплоя нового /admin/mission/drive endpoint — это даёт Кайе
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
        # FIX-31: явно говорим воркеру, какой продукт доставляем.
        # Без этого при первой доставке money_dna воркер не мог отличить
        # запись money_dna от mission и пропатчил mission Гастона.
        'productCode': product_code,
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
        print(f'6) Загружаю cover.webp и summary.html в Cloudflare R2 (prefix={prefix}, partition={r2_partition})…')
        cover_key = f'{prefix}/{r2_partition}/cover.webp'
        summary_key = f'{prefix}/{r2_partition}/summary.html'
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
    print(f'   OK: статус {product_code} для {email} → ready (inline-preview: '
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


def deliver_legacy_pdf(email: str, pdf_path: Path, product_code: str = 'mission') -> None:
    """Старый режим — только PDF без R2."""
    prefix = 'money_dna' if product_code == 'money_dna' else 'mission'
    print(f'Product : {product_code}')
    print(f'Email   : {email}')
    print(f'PDF     : {pdf_path}')
    print(f'Worker  : {WORKER_URL}')
    print('(legacy режим — без обложки и без summary)')
    print()

    service = get_drive_service()
    slug = slugify_email(email)
    ts = datetime.now().strftime('%Y-%m-%d_%H-%M')
    pdf_remote = f'{prefix}_{slug}_{ts}.pdf'

    print('1) Загружаю PDF на Google Drive…')
    pdf_file = upload_to_drive(service, pdf_path, pdf_remote, 'application/pdf')
    drive_link = pdf_file.get('webViewLink', '')
    print(f'   OK: {pdf_file["name"]}')

    print('2) Обновляю личный кабинет…')
    res = notify_worker({
        'email': email, 'status': 'ready',
        'driveLink': drive_link, 'fileName': pdf_file['name'],
    })
    print(f'   OK: статус {product_code} для {email} → ready')
    if res.get('emailSent'):
        print('   ✓ Письмо «разбор готов» отправлено клиенту.')
    elif res.get('emailError'):
        print(f'   ⚠️  Письмо не отправлено: {res["emailError"]}')
    elif res.get('previousStatus') == 'ready':
        print('   = Письмо не отправлено: миссия уже была в статусе ready.')


def main():
    args = [a for a in sys.argv[1:] if a]
    auto_yes = False
    # FIX-28: --product mission|money_dna выбирает строку Sheet под нужный
    # продукт. С 23.05.2026 флаг ОБЯЗАТЕЛЬНЫЙ — дефолта нет.
    # Это защита от тихого затирания не того продукта, когда у клиента
    # есть и миссия и деньги одновременно.
    product_code = None
    if '--yes' in args:
        auto_yes = True
        args.remove('--yes')
    if '-y' in args:
        auto_yes = True
        args.remove('-y')
    # parse --product=value or --product value
    new_args = []
    skip_next = False
    for i, a in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if a.startswith('--product='):
            product_code = a.split('=', 1)[1].strip()
            continue
        if a == '--product' and i + 1 < len(args):
            product_code = args[i + 1].strip()
            skip_next = True
            continue
        new_args.append(a)
    args = new_args
    if product_code is None:
        sys.exit(
            'СТОП: --product обязателен. Укажите --product mission или --product money_dna.\n'
            'Значение брать из колонки D Sheet:\n'
            '  «Анализ миссии звёздной души» → --product mission\n'
            '  «Архитектура Денег — код 50.56» → --product money_dna'
        )
    if product_code not in ('mission', 'money_dna'):
        sys.exit(f'--product должен быть mission или money_dna, не {product_code!r}')

    if len(args) < 2:
        print(__doc__)
        print('Использование: deliver_mission.py [--yes] --product mission|money_dna <email> <папка_или_pdf>')
        sys.exit(2)
    email = args[0].strip().lower()
    target = Path(args[1]).expanduser().resolve()

    if not EMAIL_RE.match(email):
        sys.exit(f'Email "{email}" выглядит некорректно.')
    if not target.exists():
        sys.exit(f'Путь {target} не найден.')

    if target.is_file() and target.suffix.lower() == '.pdf':
        sheets = get_sheets_service()
        sheet_info = lookup_sheet_row_for_mission(sheets, email, product_code=product_code)
        confirm_client_dispatch(email, sheet_info, target.parent, auto_yes)
        deliver_legacy_pdf(email, target, product_code=product_code)
    elif target.is_dir():
        deliver_full(email, target, auto_yes=auto_yes, product_code=product_code)
    else:
        sys.exit('Передайте папку клиента или путь к *.pdf.')

    print()
    print('Готово.')


if __name__ == '__main__':
    main()
