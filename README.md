# Скиллы пайплайна разборов

Репо обслуживает два продукта с ручной доставкой:

| Продукт | `--product` | Файл-разбор | PDF |
|---|---|---|---|
| Анализ миссии звёздной души (код 37) | `mission` | `<Имя>_<DDMMYYYY>_миссия_v2.md` | `<Имя>_<DDMMYYYY>_миссия.pdf` |
| Архитектура Денег (код 50.56) | `money_dna` | `<Имя>_<DDMMYYYY>_деньги.md` (без `_v2`) | `<Имя>_<DDMMYYYY>_деньги.pdf` |

Оркестратор и `deliver_mission.py` различают продукты по обязательному флагу `--product`. Источник истины для выбора — колонка D Google Sheet «Покупки»:
- «Анализ миссии звёздной души» → `--product mission`
- «Архитектура Денег — код 50.56» → `--product money_dna`

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
│  3-validation           │  Subagent: ШАГ 0 = money_validate.py (A–W),
│  (отдельный агент)      │  затем ручной чеклист. До 2 итераций → эскалация
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
| `pull_client.py` | `.cursor/skills/1-download/` | Скачать папки клиентов с Drive (поддерживает `--product mission\|money_dna`) |
| `money_validate.py` | `.cursor/skills/2-money-analysis/` | Жёсткий гейт-валидатор разбора ДНК денег (проверки A–W). Запуск обязателен перед показом Дарье. |
| `generate_pdf.py` | `.cursor/skills/5-pdf/` | MD → стилизованный PDF |
| `deliver_mission.py` | `.cursor/skills/6-delivery/` | Доставка в кабинет. Флаг `--product mission\|money_dna` **обязателен**. |

### Правила анализа денег — компаньоны скиллов

Все правила оперирования разборами ДНК денег лежат **внутри скиллов** (не в `.cursor/rules/`):

| Файл | Где | Назначение |
|---|---|---|
| `SKILL.md` | `2-money-analysis/` | Самодостаточный алгоритм разбора: финансовые точки, ТОП-3 цивилизаций (тиеры), 11 сфер, корневые принципы J–W |
| `money_language_style.md` | `2-money-analysis/` | Языковой стиль (эталон Виктории/Александры), банк форматов дохода, причины 1–8. Используется и скиллом любви |
| `money_validate.py` | `2-money-analysis/` | Авто-гейт A–W (см. таблицу проверок ниже) |
| `money_template.md` | `2-money-analysis/` | Шаблон структуры разбора |
| `SKILL.md` | `3-money-validation/` | Чеклист валидации (отдельный subagent): ШАГ 0 — авто-гейт `money_validate.py`, затем ручные блоки |
| `money_self_validation.md` | `3-money-validation/` | Самовалидация «глазами» (10 пунктов + блоки 1–8), которые регулярка не ловит |
| `money_analysis_errors.md` | `3-money-validation/` | Калибровка 14 частых ошибок с эталонами |

Автоматические проверки валидатора (FAIL — показывать клиенту ЗАПРЕЩЕНО):
- **A–G** — диспозиторы Раху/Кету, флагман-профессия, 3 пласта сфер, аттрактор→тень, достоинство Марса/Луны в Раке, урок-джйотиш, перегруз наставничеством.
- **J–R** — выдумка/имена звёзд из CSV, расчёты, рассуждения агента/ранжирование сил, 1 услуга/раздел, копипаст «курсы», цивилизация на Асценденте, соединения 1-го дома, книга у цивилизаций.
- **S–W** — орб=CSV (S), своё соединение раздела раскрыто как цивилизация (T), Энергодуш по смыслу не «прибит» к Сатурну (U), конкретные профессии в т.ч. в 11 сферах (V, WARN), стеллиумы раскрыты как взаимосвязь, не по одиночке (W).

Все скрипты используют `PRODUCTY_ROOT` (env) или `~/Desktop/Producty` для поиска конфига в `DariaGalactic/config/`.
Клиентские профайлы по умолчанию лежат на `D:\DariaGalactic\Профайлы клиентов`; переменная `CLIENT_PROFILES_DIR` может переопределить путь.

### Запуск `deliver_mission.py`

```bash
# Миссия
python3 .cursor/skills/6-delivery/deliver_mission.py --product mission --yes \
  client@example.com "Профайлы клиентов/Имя_contract_дата"

# Архитектура Денег
python3 .cursor/skills/6-delivery/deliver_mission.py --product money_dna --yes \
  client@example.com "Профайлы клиентов/Имя_contract_дата"
```

Если флаг `--product` не передан — скрипт остановится с подсказкой. Это защита от тихого затирания не того продукта, когда у клиента в Sheet есть и миссия, и деньги.

Дополнительно скрипт сам решает префикс файлов и R2-ключей по `--product`:

| Артефакт | mission | money_dna |
|---|---|---|
| PDF в папке клиента (вход) | `*_миссия.pdf` | `*_деньги.pdf` |
| Имя PDF на GDrive | `mission_<slug>_<ts>.pdf` | `money_dna_<slug>_<ts>.pdf` |
| Имя PNG cover на GDrive | `mission_<slug>_<ts>_cover.png` | `money_dna_<slug>_<ts>_cover.png` |
| Ключ cover.webp в R2 | `mission/<contractShort>/cover.webp` | `money_dna/<contractShort>/cover.webp` |
| Ключ summary.html в R2 | `mission/<contractShort>/summary.html` | `money_dna/<contractShort>/summary.html` |

Воркер хранит финальные `coverKey`/`summaryKey` в KV `missions:<email>` и при отдаче в кабинет читает их как есть — префикс продукта для воркера прозрачен.

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
