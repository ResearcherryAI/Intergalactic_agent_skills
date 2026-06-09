# Runtime-токены pull/delivery

Эта папка должна существовать после `git pull`, чтобы программы `1-download/pull_client.py`, `6-delivery/deliver_mission.py` и `6-delivery/_reauth.py` находили локальные доступы без обращения к `intergalactic_workers_ai/config`.

Файлы, которые должны лежать здесь локально:

- `.env`
- `gdrive_token.json`
- `cabinet_sheet_token.json`
- `client_secret_*.json`

Эти файлы игнорируются git и не коммитятся. Cloudflare deploy-токены, которые меняют код воркеров, сюда не класть.
