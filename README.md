# Скиллы пайплайна миссии

## Архитектура

```
┌─────────────────────────┐
│  0-orchestrator         │  Диспетчер: поток, гейты, триггеры
│  → read SKILL по шагам  │
└────────┬────────────────┘
         │
┌────────▼────────────────┐
│  1-download             │  pull_client.py --all / <email> / --regen-csv-for
│  → D:\DariaGalactic\    │
│    Профайлы клиентов\   │
└────────┬────────────────┘
         │
┌────────▼────────────────┐
│  2-analysis             │  CSV → MD (380-420 строк) + summary.md
│  (самодостаточный)      │  TIER, 2 слоя, дома, edge cases
└────────┬────────────────┘
         │
┌────────▼────────────────┐
│  3-validation           │  Subagent (Task tool), 14 пунктов
│  (отдельный агент)      │  До 2 итераций → эскалация
└────────┬────────────────┘
         │
    ┌────┴─────┐
┌───▼───┐  ┌───▼───┐
│4-image │  │5-pdf  │     Параллельно
│ + self │  │ gen   │
│ check  │  │ pdf.py│
└───┬────┘  └───┬───┘
    └────┬──────┘
┌────────▼────────────────┐
│  6-delivery             │  Pre-delivery gate → deliver_mission.py
│  → GDrive + R2 + Sheet  │  + git commit (без push)
└────────┬────────────────┘
         │
┌────────▼────────────────┐
│  Оркестратор: ШАГ 7     │  git push (один раз в конце сессии)
└─────────────────────────┘
```

## Скрипты

| Скрипт | Расположение | Назначение |
|---|---|---|
| `pull_client.py` | `.cursor/skills/1-download/` | Скачать папки клиентов с Drive |
| `generate_pdf.py` | `.cursor/skills/5-pdf/` | MD → стилизованный PDF |
| `deliver_mission.py` | `.cursor/skills/6-delivery/` | Доставка в кабинет |

Все скрипты используют `PRODUCTY_ROOT` (env) или `~/Desktop/Producty` для поиска конфига в `DariaGalactic/config/`.
Клиентские профайлы по умолчанию лежат на `D:\DariaGalactic\Профайлы клиентов`; переменная `CLIENT_PROFILES_DIR` может переопределить путь.

## Рабочая папка

**Единственная рабочая папка:** `D:\DariaGalactic\Профайлы клиентов\` — скачивание, анализ, delivery, git.

В проекте Cursor путь `DariaGalactic/Профайлы клиентов/` оставлен только как символическая ссылка для удобного просмотра файлов.

## Git-архив

```
D:\DariaGalactic\Профайлы клиентов\.git\
→ github.com/ResearcherryAI/IntergalacticClientsProfiles (PRIVATE)
```

Что в git: `*.md`, `*.csv`. Что НЕ в git: `*.pdf`, `*.png`, `*.jpg` (бэкапятся на GDrive в шаге 6).

## Конфиг

`DariaGalactic/config/` — `.env`, `gdrive_token.json`, `client_secret_*.json`, `cabinet_sheet_token.json`.

Если папка конфигов удалена или машина новая, runtime-креды восстанавливаются из приватного репозитория `https://github.com/ResearcherryAI/Intergalacticcreds.git`. Для `pull_client.py` и `deliver_mission.py` копировать только релевантные файлы:
- `.env`
- `client_secret_*.json`
- `gdrive_token.json`
- `cabinet_sheet_token.json`

Мастер-копии секретов, Cloudflare local-файлы и admin-drive токены не копировать без отдельной необходимости.

## Бэкап предыдущих скиллов

`.cursor/skills_backup/` — полная копия всех скиллов до реструктуризации.
