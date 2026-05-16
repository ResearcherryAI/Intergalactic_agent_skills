#!/usr/bin/env python3
r"""
pull_client.py — подтянуть клиента после оплаты в локальную папку.

Что делает (Variant B, актуальная версия):
  1. Worker сразу после оплаты сам создаёт подпапку клиента в общей
     Drive-папке «Разборы» (`GDRIVE_FOLDER_ID`) и кладёт туда
     `chart.csv` — натальную карту, посчитанную фронтом в скрытом
     iframe.
  2. Скрипт идёт в Drive, находит папки с `chart.csv` и скачивает
     их локально в `D:\DariaGalactic\Профайлы клиентов\Купившие разбор\<Имя>_<contract12>_<YYYYMMDD>\`.

Два режима запуска:

  • Точечный (по одному клиенту, например только что оплативший):
        python3 pull_client.py <email> [--contract <contractId>]
    Идёт в Worker `/admin/mission?email=…`, получает driveFolderId
    миссии, скачивает её локально. Если у клиента 2+ миссий — берёт
    первую активную (in_review / awaiting_chart) или самую свежую.
    Fallback: если у миссии нет folderId (legacy/seed), создаёт
    подпапку в «Разборы» и кладёт `birth_<contractId>.csv` (Worker
    регистрирует через `POST /admin/mission/drive`).

  • Батч (по умолчанию для синка всех актуальных клиентов):
        python3 pull_client.py --all
    Скрипт перечисляет всё содержимое общей папки «Разборы»
    (`GDRIVE_FOLDER_ID`), для каждой подпапки проверяет наличие
    `chart.csv` и докачивает локально. Уже скачанные файлы
    пропускает (idempotent — можно гонять хоть каждый день).

  • Regen CSV (без download) — для клиентов, у которых Variant B
    iframe не успел отправить карту (мобильный браузер прервал):
        python3 pull_client.py --regen-csv-for <email> [--contract <id>]
    Скрипт вызывает Worker `/admin/chart-csv/regen`:
      1. Если CSV есть в KV — Worker сразу заливает в Drive-папку.
      2. Если нет — Worker отдаёт `autoCsvUrl` (basic.html?auto_csv=1
         с birth-данными из миссии). Скрипт открывает этот URL в
         headless Chromium (Playwright), фронт сам POSTит CSV в
         `/lead/chart-csv`, после чего скрипт повторяет regen —
         Worker заливает свежий CSV в Drive.
    То же самое в точечном режиме делается автоматически (можно
    отключить флагом `--no-regen`).

Конфиги (всё в DariaGalactic/config/, см. deliver_mission.py):
  • .env c WORKER_URL, ADMIN_SECRET и GDRIVE_FOLDER_ID.
  • client_secret_*.json + gdrive_token.json.

Важно про авторизацию: локальный `gdrive_token.json` должен быть
выписан на тот же Google-аккаунт, на котором авторизован Worker
(`interviewkotilev@gmail.com`). Иначе drive.file scope не покажет
файлы, созданные Worker'ом. Если токен на другом аккаунте —
удалите `gdrive_token.json` и запустите скрипт ещё раз.

Зависимости (те же, что у deliver_mission.py):
  python3 -m pip install --upgrade google-api-python-client \\
      google-auth-httplib2 google-auth-oauthlib requests python-dotenv
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SCRIPT_DIR = Path(__file__).resolve().parent
PRODUCTY_ROOT = Path(os.environ.get(
    'PRODUCTY_ROOT',
    str(Path.home() / 'Desktop' / 'Producty')
))
CONFIG_DIR = PRODUCTY_ROOT / 'DariaGalactic' / 'config'

try:
    from dotenv import load_dotenv
    load_dotenv(CONFIG_DIR / '.env')
except ImportError:
    pass

WORKER_URL = os.environ.get(
    'WORKER_URL',
    'https://intergalactic-cabinet.duduk12250405.workers.dev',
).rstrip('/')
ADMIN_SECRET = os.environ.get('ADMIN_SECRET', '')

# Та же общая папка-контейнер, что использует Worker. Все клиентские
# подпапки лежат непосредственно в ней.
GDRIVE_FOLDER_ID = os.environ.get('GDRIVE_FOLDER_ID', '')

DEFAULT_LOCAL_ROOT = Path(os.environ.get(
    'CLIENT_PROFILES_DIR',
    os.environ.get('MISSION_LOCAL_DIR', r'D:\DariaGalactic\Профайлы клиентов\Купившие разбор'),
))

SCOPES = ['https://www.googleapis.com/auth/drive.file']
TOKEN_FILE = CONFIG_DIR / 'gdrive_token.json'
SHEET_TOKEN_FILE = CONFIG_DIR / 'cabinet_sheet_token.json'
SHEET_ID = os.environ.get(
    'SHEET_ID',
    '1X2voXTHnywDHXk1BRVNsYktrL8MtXHqxl6jhwymLzWE',
)
SHEET_SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']


# ── Google Drive auth (та же логика, что и в deliver_mission.py) ─────
def find_client_secret() -> Path:
    candidates = sorted(CONFIG_DIR.glob('client_secret*.json'))
    if not candidates:
        sys.exit(
            f'client_secret_*.json не найден в {CONFIG_DIR}.\n'
            'Скопируйте OAuth client (Desktop app) JSON туда.'
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
            flow = InstalledAppFlow.from_client_secrets_file(
                str(find_client_secret()), SCOPES,
            )
            creds = flow.run_local_server(port=0, prompt='select_account')
        TOKEN_FILE.write_text(creds.to_json())
    return build('drive', 'v3', credentials=creds)


# ── Google Sheets (фильтр по статусу) ────────────────────────────────
def get_sheets_service():
    creds = None
    if SHEET_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(SHEET_TOKEN_FILE), SHEET_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(find_client_secret()), SHEET_SCOPES,
            )
            creds = flow.run_local_server(port=0, prompt='select_account')
        SHEET_TOKEN_FILE.write_text(creds.to_json())
    return build('sheets', 'v4', credentials=creds)


def fetch_in_review_contracts() -> set[str]:
    """Читает Google Sheet, возвращает set из contract12 (последние 12 символов contractId)
    для клиентов со статусом 'В разборе у Дарьи'.
    """
    sheets = get_sheets_service()
    result = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range='Покупки!A:H',
    ).execute()
    rows = result.get('values', [])
    if not rows:
        return set()

    contracts = set()
    for row in rows[1:]:
        if len(row) < 8:
            continue
        status = (row[7] or '').strip()
        contract_id = (row[6] or '').strip()
        if status == 'В разборе у Дарьи' and contract_id:
            c12 = re.sub(r'[^A-Za-z0-9]+', '', contract_id)[-12:]
            if c12:
                contracts.add(c12)
    return contracts


# ── Helpers ──────────────────────────────────────────────────────────
def slugify_name(name: str) -> str:
    """Безопасное имя папки/файла с сохранением кириллицы."""
    name = name or 'client'
    safe = re.sub(r'[\\/:*?"<>|]+', '', name).strip()
    safe = re.sub(r'\s+', '_', safe)
    return safe[:60] or 'client'


def short_contract(cid: str) -> str:
    if not cid:
        return 'unknown'
    return re.sub(r'[^A-Za-z0-9]+', '', cid)[-12:].lstrip('-') or 'unknown'


def folder_label(mission: dict) -> str:
    """`Имя_<contract12>_<YYYYMMDD>` — стабильный человекочитаемый id.

    Зеркалирует логику Worker'а (driveFindOrCreateClientFolder), чтобы
    fallback-папка имела то же имя, что и Worker сделал бы сам.
    """
    name = mission.get('buyerName') or mission.get('name') or 'client'
    cid = mission.get('contractId') or ''
    iso = mission.get('purchasedAt') or ''
    try:
        dt = datetime.fromisoformat(iso.replace('Z', '+00:00')) if iso else datetime.utcnow()
    except Exception:
        dt = datetime.utcnow()
    return f'{slugify_name(name)}_{short_contract(cid)}_{dt:%Y%m%d}'


def fallback_birth_csv(mission: dict, email: str) -> str:
    """Минимальный CSV с данными рождения — на случай, если
    Worker не успел положить chart.csv (legacy / seed без iframe).
    deliver_mission.py всё равно потом обновит файлы в этой папке.
    """
    b = mission.get('birth') or {}
    rows = ['# Researchy mission birth-data (fallback)']
    rows.append(f'# Email;{email}')
    rows.append(f"# Имя;{mission.get('buyerName') or ''}")
    rows.append(f"# Дата рождения;{b.get('dateHuman') or ''}")
    rows.append(f"# Время;{b.get('timeHuman') or ''}")
    rows.append(f"# Город;{b.get('cityFull') or b.get('city') or ''}")
    coords = b.get('coords')
    if not coords and (b.get('lat') is not None and b.get('lng') is not None):
        coords = f"{b.get('lat')}, {b.get('lng')}"
    rows.append(f"# Координаты;{coords or ''}")
    rows.append(f"# Часовой пояс;{b.get('tzLabel') or b.get('tz') or ''}")
    rows.append(f"# UTC offset;{b.get('utc') if b.get('utc') is not None else ''}")
    rows.append(f"# Contract;{mission.get('contractId') or ''}")
    rows.append(f"# Status;{mission.get('status') or ''}")
    rows.append(f"# Purchased;{mission.get('purchasedAt') or ''}")
    return '\ufeff' + '\n'.join(rows) + '\n'


# ── Worker API ───────────────────────────────────────────────────────
def admin_headers() -> dict:
    if not ADMIN_SECRET:
        sys.exit('ADMIN_SECRET не задан в .env (DariaGalactic/config/.env).')
    return {'X-Admin-Key': ADMIN_SECRET, 'Content-Type': 'application/json'}


def fetch_missions(email: str) -> list[dict]:
    r = requests.get(
        f'{WORKER_URL}/admin/mission',
        params={'email': email},
        headers=admin_headers(),
        timeout=30,
    )
    if r.status_code == 401:
        sys.exit('Worker вернул 401: проверьте ADMIN_SECRET.')
    r.raise_for_status()
    data = r.json()
    if not data.get('ok'):
        sys.exit(f'Worker ошибка: {data}')
    return data.get('missions') or []


def post_drive_folder(email: str, mission: dict, folder_id: str, folder_url: str):
    body = {
        'email': email,
        'contractId': mission.get('contractId') or '',
        'driveFolderId': folder_id,
        'driveFolderUrl': folder_url,
    }
    r = requests.post(
        f'{WORKER_URL}/admin/mission/drive',
        json=body,
        headers=admin_headers(),
        timeout=30,
    )
    if not r.ok:
        sys.exit(f'POST /admin/mission/drive failed: {r.status_code} {r.text[:200]}')
    out = r.json()
    if not out.get('ok'):
        sys.exit(f'POST /admin/mission/drive вернул не-ok: {out}')


def regen_chart_csv_via_worker(email: str, contract_id: str | None = None,
                               csv_text: str | None = None) -> dict:
    """POST /admin/chart-csv/regen. Воркер заливает CSV в Drive (если он
    есть в KV или передан в `csv_text`), либо отдаёт `autoCsvUrl` —
    адрес `basic.html?auto_csv=1&...`, который надо открыть в headless,
    чтобы фронт сам посчитал карту и отправил CSV.

    Returns: dict вида
      { ok: bool, status?, autoCsvUrl?, driveFolderId?, driveFolderUrl?,
        chartCsvLink?, chartCsvFileId?, mission? }
    """
    body: dict = {'email': email}
    if contract_id:
        body['contractId'] = contract_id
    if csv_text:
        body['csv'] = csv_text
    r = requests.post(
        f'{WORKER_URL}/admin/chart-csv/regen',
        json=body, headers=admin_headers(), timeout=60,
    )
    if r.status_code == 401:
        sys.exit('Worker /admin/chart-csv/regen → 401: проверьте ADMIN_SECRET.')
    try:
        return r.json()
    except Exception:
        return {'ok': False, 'error': f'invalid_response_{r.status_code}', 'detail': r.text[:200]}


def trigger_auto_csv_via_browser(auto_csv_url: str, timeout_s: int = 25) -> bool:
    """Открыть `autoCsvUrl` в headless Chromium и подождать, пока фронт
    `basic.html` рассчитает карту и POSTнет её в `/lead/chart-csv`.

    Точкой завершения считаем момент, когда фронт пометит окно
    `window.__GV_CHART_CSV_DONE__ = true` (это делает app.js после
    успешного fetch). Если по таймауту флага нет — возвращаем False,
    пусть админ повторит вручную.

    Зависимость: `pip install playwright && playwright install chromium`.
    Если Playwright не установлен — печатаем подсказку и возвращаем False.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('   ! Playwright не установлен. Установите:')
        print('     python3 -m pip install playwright')
        print('     python3 -m playwright install chromium')
        print(f'   ! Либо откройте URL вручную в обычном браузере и подождите 10 сек:')
        print(f'     {auto_csv_url}')
        return False

    print(f'   → headless Chromium открывает {auto_csv_url[:80]}…')
    posted = {'value': False}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()

            # Слушаем POST /lead/chart-csv — это финальная точка.
            def on_response(resp):
                try:
                    if '/lead/chart-csv' in resp.url and resp.request.method == 'POST':
                        if resp.status == 200:
                            posted['value'] = True
                except Exception:
                    pass
            page.on('response', on_response)

            page.goto(auto_csv_url, timeout=timeout_s * 1000)
            # Ждём либо POST, либо флаг __GV_CHART_CSV_DONE__, либо таймаут.
            deadline = timeout_s * 1000
            try:
                page.wait_for_function(
                    'window.__GV_CHART_CSV_DONE__ === true || window.__GV_CHART_CSV_DONE__ === "ok"',
                    timeout=deadline,
                )
                posted['value'] = True
            except Exception:
                # Возможно фронт ещё не выставляет флаг — fallback на observed POST.
                pass
            browser.close()
    except Exception as e:
        print(f'   ! headless ошибка: {e}')
        return False
    return posted['value']


def regen_chart_csv_for(email: str, contract_id: str | None = None,
                        timeout_s: int = 25) -> dict:
    """Полный цикл «починки» CSV для клиента:
        1) POST /admin/chart-csv/regen → если CSV уже есть в KV, заливает
           в Drive и возвращает ok=true.
        2) Иначе берёт `autoCsvUrl`, открывает в headless Chromium,
           ждёт пока фронт отправит CSV, затем повторяет regen.
    """
    print(f'→ Regen CSV для {email}'
          + (f' (contract {contract_id})' if contract_id else ''))
    resp = regen_chart_csv_via_worker(email, contract_id)
    if resp.get('ok'):
        print('   ✓ CSV найден в KV и залит в Drive:')
        print(f'     chartCsvLink: {resp.get("chartCsvLink")}')
        print(f'     folder:       {resp.get("driveFolderUrl")}')
        return resp
    if resp.get('status') != 'no_csv':
        print(f'   ! Worker ответ не-ok без autoCsvUrl: {resp}')
        return resp

    auto_url = resp.get('autoCsvUrl') or ''
    folder_id = resp.get('driveFolderId') or ''
    print(f'   = CSV нет ни в KV, ни в Drive. Запускаем headless calc.')
    if not auto_url:
        print('   ! autoCsvUrl пуст — нет birth-данных у миссии.')
        return resp

    triggered = trigger_auto_csv_via_browser(auto_url, timeout_s=timeout_s)
    if not triggered:
        print('   ! headless calc не завершился за таймаут. Повторите позже.')
        return resp

    print('   ↻ headless завершён, повторяем regen…')
    resp2 = regen_chart_csv_via_worker(email, contract_id)
    if resp2.get('ok'):
        print('   ✓ CSV сгенерирован и залит в Drive:')
        print(f'     chartCsvLink: {resp2.get("chartCsvLink")}')
        print(f'     folder:       {resp2.get("driveFolderUrl") or folder_id}')
    else:
        print(f'   ! После headless всё ещё нет CSV: {resp2}')
    return resp2


# ── Drive ops ────────────────────────────────────────────────────────
def create_client_folder(service, parent_id: str, name: str) -> dict:
    """Создаёт subfolder в `parent_id` («Разборы»). Используется как
    fallback, если Worker не создал папку (legacy)."""
    meta = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id],
    }
    return service.files().create(body=meta, fields='id,webViewLink,name').execute()


def upload_csv_text(service, parent_id: str, name: str, content: str) -> dict:
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode('utf-8')),
        mimetype='text/csv',
        resumable=False,
    )
    meta = {'name': name, 'parents': [parent_id]}
    return service.files().create(
        body=meta, media_body=media, fields='id,name,webViewLink',
    ).execute()


def list_folder_files(service, folder_id: str) -> list[dict]:
    files = []
    page_token = None
    while True:
        res = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields='nextPageToken, files(id,name,mimeType,size)',
            pageToken=page_token,
        ).execute()
        files.extend(res.get('files', []))
        page_token = res.get('nextPageToken')
        if not page_token:
            break
    return files


def download_file(service, file_id: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(dest, 'wb')
    downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.close()


# ── Mission selection ────────────────────────────────────────────────
STATUS_PRIORITY = {'in_review': 0, 'awaiting_chart': 1, 'ready': 2}


def pick_mission(missions: list[dict], contract: str | None) -> dict:
    if not missions:
        sys.exit('У этого email нет миссий в кабинете.')
    if contract:
        for m in missions:
            if (m.get('contractId') or '').strip() == contract.strip():
                return m
        sys.exit(f'Миссия с contractId={contract} не найдена.')

    def sort_key(m):
        st = STATUS_PRIORITY.get(m.get('status'), 9)
        no_folder = 0 if not m.get('driveFolderId') else 1
        ts = m.get('purchasedAt') or ''
        return (st, no_folder, '0' if not ts else '0', -1 * (len(ts)), ts)

    missions_sorted = sorted(missions, key=sort_key)
    return missions_sorted[0]


# ── Sync helpers ─────────────────────────────────────────────────────
def sync_folder_to_local(service, folder_id: str, folder_name: str, out_root: Path,
                         require_chart_csv: bool = False) -> tuple[int, int, bool]:
    """Синкает содержимое Drive-папки в локальную <out_root>/<folder_name>/.

    Возвращает (downloaded, skipped, has_chart_csv).
    Если require_chart_csv=True и в папке нет CSV-карты — синк пропускается
    и возвращается (0, 0, False).

    Карта Worker'ом кладётся как `karta_<short12>.csv` (default из
    `/lead/chart-csv`); deliver_mission.py может оставлять `chart.csv`
    или `karta_*.csv`. Считаем, что любой `.csv`-файл в папке = карта
    готова к скачиванию.
    """
    files = list_folder_files(service, folder_id)
    has_chart_csv = any(
        (f.get('name') or '').lower().endswith('.csv') for f in files
    )
    if require_chart_csv and not has_chart_csv:
        return (0, 0, False)

    out_dir = out_root / folder_name
    out_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    skipped = 0
    for f in files:
        if f.get('mimeType') == 'application/vnd.google-apps.folder':
            continue
        dest = out_dir / f['name']
        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            continue
        download_file(service, f['id'], dest)
        downloaded += 1
    return (downloaded, skipped, has_chart_csv)


def list_root_subfolders(service, parent_id: str) -> list[dict]:
    """Все подпапки общей «Разборы». Без trashed, только folder MIME."""
    folders = []
    page_token = None
    q = (
        f"'{parent_id}' in parents and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        "trashed = false"
    )
    while True:
        res = service.files().list(
            q=q, fields='nextPageToken, files(id,name,webViewLink)',
            pageToken=page_token, pageSize=200,
        ).execute()
        folders.extend(res.get('files', []))
        page_token = res.get('nextPageToken')
        if not page_token:
            break
    return folders


# ── Main ─────────────────────────────────────────────────────────────
def run_single(args):
    email = args.email.strip().lower()
    if '@' not in email:
        sys.exit(f'Невалидный email: {email}')

    print(f'→ Worker {WORKER_URL}')
    missions = fetch_missions(email)
    print(f'→ Получено миссий: {len(missions)}')
    for i, m in enumerate(missions):
        print(f'    [{i}] {m.get("buyerName") or "":30s}  status={m.get("status") or "":14s}  '
              f'contractId={m.get("contractId")}  drive={"yes" if m.get("driveFolderId") else "no"}')

    mission = pick_mission(missions, args.contract)
    cid = mission.get('contractId') or ''
    print(f'\n→ Выбрана миссия: {mission.get("buyerName")} ({cid})  status={mission.get("status")}')

    service = get_drive_service()

    folder_id = mission.get('driveFolderId')
    folder_url = mission.get('driveFolderUrl') or ''
    folder_name = mission.get('driveFolderName') or folder_label(mission)

    if folder_id:
        print(f'→ Drive folder уже существует (создан Worker\'ом): {folder_id}')
        print(f'   URL: {folder_url or f"https://drive.google.com/drive/folders/{folder_id}"}')
    else:
        # Fallback: Worker не создал папку (legacy / сценарий без Variant B).
        if not GDRIVE_FOLDER_ID:
            sys.exit('GDRIVE_FOLDER_ID не задан в .env, fallback невозможен.')
        print(f'→ У миссии нет folderId, создаём папку: {folder_name}')
        f = create_client_folder(service, GDRIVE_FOLDER_ID, folder_name)
        folder_id = f['id']
        folder_url = f.get('webViewLink') or f'https://drive.google.com/drive/folders/{folder_id}'
        print(f'   id={folder_id}  url={folder_url}')

        # Минимальный birth-data CSV — пока chart.csv от basic.html не подкинули.
        csv_name = f'birth_{short_contract(cid)}.csv'
        upload_csv_text(service, folder_id, csv_name, fallback_birth_csv(mission, email))
        print(f'   ↑ uploaded {csv_name}')

        post_drive_folder(email, mission, folder_id, folder_url)
        print('   ✓ зарегистрировано в Worker (Sheet column O обновлена)')

    out_root = Path(args.out_dir).expanduser()
    print(f'\n→ Локальная папка: {out_root / folder_name}')

    # Если воркер не залил CSV (Variant B iframe прервался) — авто-regen.
    has_csv_link = bool(mission.get('chartCsvLink'))
    if not has_csv_link and not getattr(args, 'no_regen', False):
        try:
            drive_files = list_folder_files(service, folder_id)
            has_csv_drive = any((f.get('name') or '').lower().endswith('.csv') for f in drive_files)
        except Exception:
            has_csv_drive = False
        if not has_csv_drive:
            print('\n→ В Drive folder нет .csv карты — запускаем regen-цикл:')
            regen_chart_csv_for(email, cid, timeout_s=int(getattr(args, 'regen_timeout', 30)))

    try:
        downloaded, skipped, _ = sync_folder_to_local(
            service, folder_id, folder_name, out_root, require_chart_csv=False,
        )
    except Exception as e:
        sys.exit(
            f'\n!! Не удалось прочитать содержимое Drive-папки: {e}\n'
            'Скорее всего gdrive_token.json авторизован НЕ на тот аккаунт,\n'
            'на котором Worker создал папку. Проверьте: Worker работает под\n'
            '«interviewkotilev@gmail.com». Удалите gdrive_token.json и\n'
            'переавторизуйтесь под этим же аккаунтом.'
        )
    print(f'→ Скачано: {downloaded}, пропущено (уже есть): {skipped}')

    print('\nГотово.')
    print(f'  • Drive: {folder_url}')
    print(f'  • Локально: {out_root / folder_name}')
    print('\nДальше: разбор кладёте в эту же папку (PDF + Generated_image.png + summary.md),')
    print('затем запускаете deliver_mission.py с этим email и путём.')


def run_all(args):
    """Синкаем ТОЛЬКО клиентов со статусом 'В разборе у Дарьи' из Google Sheet."""
    if not GDRIVE_FOLDER_ID:
        sys.exit('GDRIVE_FOLDER_ID не задан в .env. Без него --all не умеет.')

    out_root = Path(args.out_dir).expanduser()
    out_root.mkdir(parents=True, exist_ok=True)

    # ШАГ 1: Читаем Sheet — только клиенты «В разборе у Дарьи»
    print('→ Читаю Google Sheet для фильтра по статусу…')
    try:
        in_review = fetch_in_review_contracts()
    except Exception as e:
        sys.exit(f'!! Не удалось прочитать Sheet: {e}\n'
                 f'Проверьте {SHEET_TOKEN_FILE}')
    print(f'→ В Sheet статус «В разборе у Дарьи»: {len(in_review)} клиентов')

    if not in_review:
        print('   Нет клиентов со статусом «В разборе». Нечего скачивать.')
        return

    # ШАГ 2: Получаем все папки с GDrive
    print(f'→ Читаю подпапки из Drive «Разборы» ({GDRIVE_FOLDER_ID})')
    service = get_drive_service()
    try:
        folders = list_root_subfolders(service, GDRIVE_FOLDER_ID)
    except Exception as e:
        sys.exit(
            f'\n!! Не удалось прочитать содержимое «Разборы»: {e}\n'
            'Проверьте gdrive_token.json: должен быть на том же Google\n'
            'аккаунте, что у Worker (interviewkotilev@gmail.com).'
        )
    print(f'→ Подпапок в Drive: {len(folders)}')

    # ШАГ 3: Определяем, какие клиенты уже скачаны локально
    local_contracts = set()
    local_root = Path(out_root)
    if local_root.exists():
        for d in local_root.iterdir():
            if d.is_dir():
                for part in d.name.split('_'):
                    clean = re.sub(r'[^A-Za-z0-9]', '', part)
                    if len(clean) >= 10:
                        local_contracts.add(clean)

    # ШАГ 4: Фильтруем — только «В разборе» И ещё не скачаны локально
    matched = []
    already_local = []
    for f in folders:
        name = f['name']
        folder_contract = None
        for part in name.split('_'):
            clean = re.sub(r'[^A-Za-z0-9]', '', part)
            if len(clean) >= 10 and clean in in_review:
                folder_contract = clean
                break
        if not folder_contract:
            continue
        if folder_contract in local_contracts:
            already_local.append(name)
            continue
        matched.append(f)

    print(f'→ «В разборе» на GDrive: {len(matched) + len(already_local)}')
    print(f'→ Уже скачаны локально: {len(already_local)}')
    print(f'→ Новых для скачивания: {len(matched)}')

    if len(matched) > 15:
        print(f'   ⚠️ ВНИМАНИЕ: >15 новых клиентов ({len(matched)}). Проверьте Sheet.')

    if not matched:
        print('   Все клиенты «В разборе» уже скачаны. Нечего докачивать.')
        return

    # ШАГ 5: Скачиваем только новых
    pulled = 0
    skipped_no_csv = 0
    total_downloaded = 0
    total_skipped = 0
    for f in matched:
        name = f['name']
        try:
            dl, sk, has_csv = sync_folder_to_local(
                service, f['id'], name, out_root, require_chart_csv=True,
            )
        except Exception as e:
            print(f'   ! {name:50s} sync error: {e}')
            continue
        if not has_csv:
            skipped_no_csv += 1
            print(f'   = {name:50s} (нет chart.csv — пропуск)')
            continue
        pulled += 1
        total_downloaded += dl
        total_skipped += sk
        print(f'   ↓ {name:50s} downloaded={dl} skipped={sk}')

    print(f'\nГотово.  Скачано: {pulled} из {len(matched)} «В разборе».')
    print(f'  • Скачано файлов: {total_downloaded}')
    print(f'  • Пропущено (уже локально): {total_skipped}')
    print(f'  • Без CSV: {skipped_no_csv}')
    print(f'  • Локально: {out_root}')


def run_regen(args):
    """`--regen-csv-for <email>`: только перегенерация CSV, без download.
    Полезно, когда воркер не залил CSV (мобильный браузер прервал
    Variant B iframe). Скрипт сам откроет headless calc и повторит regen.
    """
    email = (args.regen_csv_for or '').strip().lower()
    if '@' not in email:
        sys.exit(f'Невалидный email: {email}')
    if not ADMIN_SECRET:
        sys.exit('ADMIN_SECRET не задан в .env.')

    resp = regen_chart_csv_for(
        email, args.contract, timeout_s=int(args.regen_timeout),
    )
    if resp.get('ok'):
        print('\nГотово. Теперь можно сделать pull:')
        print(f'  python3 pull_client.py {email}')
        return 0
    print(f'\n! Regen не завершился. Ответ: {resp}')
    return 1


def main():
    ap = argparse.ArgumentParser(
        description='Pull client folder(s) from Drive «Разборы» to local',
    )
    ap.add_argument('email', nargs='?', default=None,
                    help='Email клиента (опционально; без него — режим --all)')
    ap.add_argument('--all', action='store_true',
                    help='Синк всех подпапок «Разборы» с chart.csv (батч-режим)')
    ap.add_argument('--contract', default=None,
                    help='(точечный режим / regen) Конкретный contractId, если 2+ миссий')
    ap.add_argument('--out-dir', default=str(DEFAULT_LOCAL_ROOT),
                    help='Локальная папка-родитель (по умолчанию Профайлы клиентов)')
    ap.add_argument('--regen-csv-for', default=None, metavar='EMAIL',
                    help='Только regen CSV для клиента (без download). '
                         'Воркер заливает CSV из KV, либо скрипт открывает '
                         'autoCsvUrl в headless Chromium и повторяет.')
    ap.add_argument('--no-regen', action='store_true',
                    help='В точечном режиме отключить авто-regen, если у миссии нет CSV.')
    ap.add_argument('--regen-timeout', default=30, type=int,
                    help='Таймаут (сек) headless calc при regen (default 30).')
    args = ap.parse_args()

    if args.regen_csv_for:
        sys.exit(run_regen(args))
    if args.all or not args.email:
        run_all(args)
    else:
        run_single(args)


if __name__ == '__main__':
    main()
