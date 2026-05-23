"""One-shot: get Google OAuth token with full drive scope.

Поднимает локальный сервер на http://localhost:8888 для приёма OAuth-redirect,
печатает ОДИН URL для браузера и ждёт, пока пользователь авторизуется.

ВАЖНО: не используем flow.run_local_server() — он внутри генерирует ВТОРОЙ
auth_url с новым state, из-за чего возникает MismatchingStateError, если
пользователь открыл наш напечатанный URL. Принимаем callback сами и
обмениваем code на token через flow.fetch_token().
"""
import os
# Разрешить, чтобы Google вернул больше scopes, чем мы запросили
# (если у токена уже выписан drive.file, Google вернёт drive + drive.file).
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

import sys
import io
import urllib.parse
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CONFIG = Path(__file__).resolve().parent.parent.parent.parent / 'DariaGalactic' / 'config'
load_dotenv(CONFIG / '.env')

from google_auth_oauthlib.flow import InstalledAppFlow

cs = sorted(CONFIG.glob('client_secret*.json'))[0]
SCOPES = ['https://www.googleapis.com/auth/drive']
REDIRECT_PORT = 8888
REDIRECT_URI = f'http://localhost:{REDIRECT_PORT}/'

print(f'Client secret: {cs.name}')
print(f'Token will be saved to: {CONFIG / "gdrive_token.json"}')
print()
sys.stdout.flush()

flow = InstalledAppFlow.from_client_secrets_file(str(cs), SCOPES)
flow.redirect_uri = REDIRECT_URI

auth_url, expected_state = flow.authorization_url(
    prompt='consent', access_type='offline'
)

print('=' * 60)
print('ОТКРОЙ ЭТУ ССЫЛКУ В БРАУЗЕРЕ:')
print()
print(auth_url)
print()
print('=' * 60)
print(f'После авторизации Google перекинет на {REDIRECT_URI}')
sys.stdout.flush()


received = {}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        received.update(params)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        if 'code' in params:
            self.wfile.write(
                '<h2>OK. Можно закрыть вкладку и вернуться в терминал.</h2>'.encode('utf-8')
            )
        else:
            err = params.get('error', 'unknown')
            self.wfile.write(
                f'<h2>Ошибка авторизации: {err}</h2>'.encode('utf-8')
            )

    def log_message(self, *args, **kwargs):
        pass


server = HTTPServer(('127.0.0.1', REDIRECT_PORT), CallbackHandler)
print(f'Сервер слушает {REDIRECT_URI}, жду redirect...')
sys.stdout.flush()

while 'code' not in received and 'error' not in received:
    server.handle_request()

if 'error' in received:
    print(f'\n❌ Google вернул ошибку: {received["error"]}')
    sys.exit(1)

if received.get('state') != expected_state:
    print(f'\n❌ State mismatch. expected={expected_state} got={received.get("state")}')
    sys.exit(1)

print('\nCode получен, обмениваю на токен...')
sys.stdout.flush()
flow.fetch_token(code=received['code'])
creds = flow.credentials

(CONFIG / 'gdrive_token.json').write_text(creds.to_json())
print('\n=== Токен сохранён в gdrive_token.json ===')
print(f'Scopes: {creds.scopes}')
