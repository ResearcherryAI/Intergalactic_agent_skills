---
name: mission-delivery
description: Отправка готового разбора миссии в личный кабинет клиента и обновление статуса в Google Sheet. Использовать когда нужно отправить разбор, опубликовать, доставить клиенту, выложить в кабинет.
---

# Отправка разбора на сайт

## ⛔ КРИТИЧЕСКИЕ ПРАВИЛА (нарушение = инцидент с клиентом)

1. **НИКОГДА не отправлять без явного разрешения Дарьи в этом чате.** Автономная отправка = критический инцидент.
2. **Email — ТОЛЬКО из колонки B Google Sheet.** Не из памяти, не из имени папки, не из предыдущих чатов.
3. **«Sheet match: НЕ НАЙДЕНО» = НЕМЕДЛЕННАЯ ОСТАНОВКА.** Не продолжать ни при каких условиях.
4. **Порядок аргументов: `deliver_mission.py <EMAIL> <ПУТЬ>`** — EMAIL ПЕРВЫЙ, путь ВТОРОЙ.
5. **ИДЕНТИФИКАЦИЯ КЛИЕНТА — ТОЛЬКО по платежу в Sheet (контракт + email + дата рождения).** Никогда не выбирать клиента по совпадению имени папки. Если в системе несколько Татьян / Ольг / Любовей — ОБЯЗАТЕЛЬНО сверить дату рождения, contractId и колонку D (продукт) с тем, что заказывал клиент. Ошибка с однофамильцем = инцидент.

## PRE-DELIVERY CHECKLIST (БЛОКИРУЮЩИЙ)

**Общие пункты (для любого продукта):**

- [ ] Флаг `--product` указан явно (`mission`, `money_dna` или `love`). Брать значение из колонки D Sheet:
  - «Анализ миссии звёздной души» → `--product mission`
  - «Архитектура Денег — код 50.56» → `--product money_dna`
  - «ДНК неземной любви — код 44» → `--product love`
  - Без флага НЕ запускать (даже если у клиента только один продукт).
- [ ] `summary.md` существует, frontmatter валиден (3 секции)
- [ ] `Generated_image.png` существует, >100KB
- [ ] Email взят из Sheet (не из памяти)
- [ ] Имя в файле = имя в Sheet
- [ ] Дата в файле = дата в Sheet
- [ ] Статус в Sheet ∈ {«Разбор АИ готов (на проверке у Кайи)», «В разборе у Кайи Каэн»}
- [ ] Получено явное «можно отправлять» от Дарьи в чате

**Для `--product mission`:**

- [ ] `<Имя>_<DDMMYYYY>_миссия.pdf` существует, >500KB (собран из v2 после AI-агента)
- [ ] `<Имя>_<DDMMYYYY>_миссия_v2.md` существует (для новых клиентов с AI-флоу)
- [ ] `benchmark_report.md` существует, score v2 ≥ 0.90

**Для `--product money_dna`:**

- [ ] `<Имя>_<DDMMYYYY>_деньги.pdf` существует, **>500KB** (если меньше — почти всегда «голый» PDF без CSS, пересобрать через `generate_money_pdf.py`)
- [ ] PDF собран ТОЛЬКО через `.cursor/skills/5-pdf/generate_money_pdf.py` — НЕ через прямой `pandoc → chrome --headless`
- [ ] PDF не содержит локальных ссылок: `python -c "d=open('<pdf>','rb').read(); assert b'file:///' not in d and b'D:/DariaGalactic' not in d"`
- [ ] `<Имя>_<DDMMYYYY>_деньги.md` существует (у денег нет v2 — только одна версия)
- [ ] `benchmark_money_report.md` существует, score ≥ 0.90 (или эквивалент из `3-money-validation`)
- [ ] `Generated_image.png` существует (это требуется для `--product money_dna`, парсер ищет именно `Generated_image.png` как cover)
- [ ] **`Generated_image.png` — это ИМЕННО картинка ДНК денег**, а не обложка миссии. Если в папке клиента уже есть `mission_*_cover.png` или `<Имя>_финансовая_ДНК.png` — сравнить размеры с `Generated_image.png`. Если совпадают с обложкой миссии — заменить на финансовую ДНК.
- [ ] **`summary.md` существует в ЭТОЙ ЖЕ папке (money).** Без `summary.md` скрипт НЕ загрузит обложку в R2 (шаг 4–6 будет пропущен) и сайт покажет СТАРУЮ картинку. Это критично: `summary.md` = триггер для R2-обложки. Если его нет — создать ПЕРЕД запуском delivery по шаблону (frontmatter + 3 секции: «Ваш дар», «Ваш вызов», «Что делать»).

**Для `--product love` (ДНК неземной любви — код 44):**

- [ ] `<Имя>_<DDMMYYYY>_любовь.pdf` существует, **>500KB** (собран через `generate_money_pdf.py` с `--header "...Алгоритм любви"`)
- [ ] PDF не содержит локальных ссылок (`file:///`, `D:/DariaGalactic`)
- [ ] `<Имя>_<DDMMYYYY>_любовь.md` существует, валидация любви пройдена
- [ ] Любовная обложка лежит ОТДЕЛЬНО от денежной/миссийной: имя содержит «любовь» (`<Имя>_<DDMMYYYY>_любовь_ДНК.png`) или `Generated_image_love.png`. Скрипт для love НЕ берёт `Generated_image.png` (она занята деньгами/миссией, когда продукты в одной папке).
- [ ] `summary_love.md` существует в той же папке (отдельный от `summary.md`; иначе кабинет не покажет inline-preview любви). Frontmatter + 3 секции «Ваш дар / Ваш вызов / Что делать».
- [ ] Воркер `intergalactic-cabinet` задеплоен с поддержкой `productCode: love` (FIX-44) и фронт `4_сайт/me/me.js` + `product_catalog.json` (продукт `love`) выкачены. Без деплоя кабинет не покажет отдельный блок любви.
- [ ] CLI-флаг для оператора: `--product love`. Внутри ЛК продукт хранится как `productCode: love_dna`, потому что фронт `/me` ждёт массив `loveDnas`.

**Нормализация имён файлов перед запуском (`--product money_dna`):**

Анализ часто сохраняет файлы как `<Имя>_<DDMMYYYY>_ДНК_денег.md/.pdf` и `<Имя>_<DDMMYYYY>_финансовая_ДНК.png` — это устаревший формат. Перед delivery ОБЯЗАТЕЛЬНО переименовать в формат delivery:

```powershell
# Если в папке клиента файлы старого формата:
Rename-Item "<папка>\<Имя>_<DDMMYYYY>_ДНК_денег.md"  "<Имя>_<DDMMYYYY>_деньги.md"
Rename-Item "<папка>\<Имя>_<DDMMYYYY>_ДНК_денег.pdf" "<Имя>_<DDMMYYYY>_деньги.pdf"
Rename-Item "<папка>\<Имя>_<DDMMYYYY>_финансовая_ДНК.png" "Generated_image.png"
```

В `summary.md` также проверить, что `cover: Generated_image.png` (не старое имя).

Если хотя бы один пункт не прошёл — СТОП, не запускать.

## Скрипт

```
.cursor/skills/6-delivery/deliver_mission.py
```

Токены: `токены/` внутри репо скиллов — `.env`, `client_secret_*.json`, `gdrive_token.json`, `cabinet_sheet_token.json`.

Если папка `токены/` удалена или машина новая, восстановить runtime-креды из приватного репозитория `https://github.com/ResearcherryAI/Intergalacticcreds.git`. Для delivery нужны только `.env`, `client_secret_*.json`, `gdrive_token.json`, `cabinet_sheet_token.json`. Cloudflare deploy-токены, которые меняют код воркеров, сюда не копировать.

## Формат вызова

```powershell
python ".cursor/skills/6-delivery/deliver_mission.py" --yes <email_клиента> "D:\DariaGalactic\Профайлы клиентов\<папка_клиента>"
```

Если передать только имя папки клиента, скрипт будет искать её внутри `D:\DariaGalactic\Профайлы клиентов\`. Для другого расположения можно задать `CLIENT_PROFILES_DIR`.

**Третий аргумент (опционально)** — полный contractId из колонки F:
```powershell
python ".cursor/skills/6-delivery/deliver_mission.py" --yes client@mail.ru "D:\DariaGalactic\Профайлы клиентов\<папка_клиента>" "uuid-contractId"
```

### 🆕 FIX-28: `--product mission|money_dna`

Если у одного email есть и mission, и money_dna — указать, какой продукт доставляем:
```powershell
python ".cursor/skills/6-delivery/deliver_mission.py" --yes --product mission <email> "<папка>"
python ".cursor/skills/6-delivery/deliver_mission.py" --yes --product money_dna <email> "<папка>"
python ".cursor/skills/6-delivery/deliver_mission.py" --yes --product love <email> "<папка>"
```

Без `--product` по умолчанию = `mission` (обратная совместимость). Скрипт фильтрует строки Sheet по ключевым словам колонки D:
- `mission` → «миссия», «миссии»
- `money_dna` → «архитектур», «денег», «50.56»

### 🆕 PDF собирается из v2 (после AI-агента)

PDF, который заливается на Drive и в кабинет, должен быть собран из `<Имя>_<DDMMYYYY>_миссия_v2.md` (доработанной версии после AI-агента), а НЕ из raw `_миссия.md` от агента. Raw остаётся в папке клиента для аудита.

Проверка перед запуском: `dir <папка> | findstr миссия` → должен быть и raw, и v2. PDF имя содержит `_миссия.pdf` без суффикса v2 (клиент видит обычное имя), но содержимое из v2.

## Что делает скрипт

1. Лукап Sheet → contractId, строка, имя, дата, город, телефон (col P)
2. **ПРОВЕРКА КЛИЕНТА** — показывает данные, падает при несовпадении
3. Создаёт/находит подпапку клиента в Drive
4. Загружает PDF и обложку на Drive
5. Парсит `summary.md`, WebP + HTML в R2
6. Worker обновляет KV и Sheet → статус «Готов · выдан клиенту»
7. Worker отправляет email + WhatsApp клиенту

## Архивация бинарников на GDrive

PDF и PNG не попадают в git. Бэкап через rclone:
```powershell
# для --product mission
rclone copy "<папка_клиента>/Generated_image.png" "gdrive:DariaGalactic/Профайлы клиентов/<имя_папки>/"
rclone copy "<папка_клиента>/<Имя>_миссия.pdf" "gdrive:DariaGalactic/Профайлы клиентов/<имя_папки>/"

# для --product money_dna
rclone copy "<папка_клиента>/Generated_image.png" "gdrive:DariaGalactic/Профайлы клиентов/<имя_папки>/"
rclone copy "<папка_клиента>/<Имя>_деньги.pdf" "gdrive:DariaGalactic/Профайлы клиентов/<имя_папки>/"
```

## Логика частичного успеха

| Канал | Fail | Действие |
|---|---|---|
| Cabinet + R2 | OK | Статус Sheet → «Готов» (mandatory) |
| Email (Resend) | 429/5xx | Пометка «email_pending», retry позже |
| WhatsApp | Fail | Пометка «whatsapp_pending», retry позже |
| Cabinet/R2 | Fail | Статус НЕ обновляется, эскалация |

## Git commit после успешной доставки

**Раздельные коммиты — raw (AI-снапшот) и v2 (правки Кайи).** Это нужно для аудита: всегда видно, что писал агент и что дорабатывала Кайя.

> Замените `<product_human>` на «миссия» или «деньги» в зависимости от `--product`.
> Для `--product money_dna` шага «v2» нет — у денег одна версия `_деньги.md`.

### Для `--product mission`:

```powershell
cd "D:\DariaGalactic\Профайлы клиентов"

# 1) Снапшот AI-выхода (raw от агента) — отдельный коммит
git add "<папка_клиента>/<Имя>_<DDMMYYYY>_миссия.md"
git add "<папка_клиента>/karta_*.csv"
git commit -m "[ai-snapshot] <Имя> <DDMMYYYY> — raw разбор миссии от intergalactic-agent"

# 2) Доработка Кайи (v2 + benchmark_report + summary + image)
git add "<папка_клиента>/<Имя>_<DDMMYYYY>_миссия_v2.md"
git add "<папка_клиента>/benchmark_report.md"
git add "<папка_клиента>/summary.md"
git commit -m "[v2-edits] <Имя> <DDMMYYYY> — доработка Кайи миссия, score X.XX"

# 3) Доставка (статус ready, ссылки в Sheet)
git commit --allow-empty -m "[delivery] <Имя> <DDMMYYYY> — миссия выдана клиенту"
```

### Для `--product money_dna`:

```powershell
cd "D:\DariaGalactic\Профайлы клиентов"

# 1) Разбор + summary + image (у денег одна версия, без raw/v2 split)
git add "<папка_клиента>/<Имя>_<DDMMYYYY>_деньги.md"
git add "<папка_клиента>/karta_*.csv"
git add "<папка_клиента>/benchmark_money_report.md"
git add "<папка_клиента>/summary.md"
git commit -m "[money-dna] <Имя> <DDMMYYYY> — разбор денег готов, score X.XX"

# 2) Доставка
git commit --allow-empty -m "[delivery] <Имя> <DDMMYYYY> — деньги выданы клиенту"
```

Если raw уже был закоммичен при первом pull-е — пропустить шаг 1.

Git push выполняется ОДИН РАЗ в конце сессии через оркестратор (ШАГ 7).

## Очистка C: после push (ОБЯЗАТЕЛЬНО)

После git push в конце сессии — обязательно выполнить очистку C:\, чтобы не допустить заполнение диска:

```powershell
# 1. Упаковать loose git objects (главный пожиратель места)
cd "c:\Users\Кири\Desktop\Producty\DariaGalactic"
git gc --prune=now

# 2. Очистить temp (Chrome headless, pandoc, ps-scripts)
Remove-Item "$env:TEMP\chrome-*" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$env:TEMP\puppeteer_*" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$env:TEMP\tmp*" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$env:TEMP\ps-script-*" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:TEMP\*.tmp" -Force -ErrorAction SilentlyContinue

# 3. Удалить одноразовые скрипты из .cursor/tools/ (если создавались в сессии)
# Не удалять: source_check.py, build_index.py, sync_to_gdrive.py, upload_as_gdoc.py и другие постоянные инструменты

# 4. Проверить свободное место
$free = [math]::Round((Get-PSDrive C).Free/1MB)
Write-Output "C: свободно: $free MB"
if ($free -lt 500) { Write-Output "⚠️ КРИТИЧНО: <500 MB свободно на C:!" }
```

**Правило:** если после очистки <500 MB — эскалация к Кириллу/Дарье. Не продолжать работу с забитым диском.

## Лог проверки (обязательно вывести перед запуском)

```
✅ ПРОВЕРКА ДОСТАВКИ:
- Product: [mission | money_dna]   ← ОБЯЗАТЕЛЬНО, должно совпадать с --product
- Email из Sheet: [email]
- Строка Sheet: [номер]
- Имя: [имя] — файл: [имя из папки] → ✓/✗
- Дата рождения: [дата] — файл: [DDMMYYYY] → ✓/✗
- contractId: [uuid]
- Телефон (WA): [phone или —]
```

## OUTPUT-гейт

- [ ] Статус в Sheet обновлён
- [ ] Бинарники скопированы на GDrive
- [ ] Git commit создан
- [ ] Запись в лог клиента: каналы, причины fail

## Формат `summary.md` (контракт парсера)

- Файл начинается с `---`
- В frontmatter: **`civilization`**, **`headline`**, рекомендуется **`cover`**
- После frontmatter: 3 заголовка `## …`, под каждым минимум один `- текст`
- Секции: **Ваш дар** → **Ваш вызов** → **Что делать**

```markdown
---
civilization: Лира
headline: Краткий тезис без точки в конце
cover: Generated_image.png
---

## Ваш дар

- первый пункт

## Ваш вызов

- первый пункт

## Что делать

- первый пункт
```

## Обработка ошибок

| Ошибка | Причина | Решение |
|---|---|---|
| `СТОП: для этого email нет строки…` | Email не найден | Перечитать Sheet |
| 401 Unauthorized | Протух токен | Удалить `gdrive_token.json`, перезапустить |
| R2 upload failed | R2 token / bucket | Проверить `токены/.env`; deploy-токен воркеров сюда не класть |
| Worker POST failed | Worker недоступен | Проверить `WORKER_URL` |
| `отсутствует frontmatter` | Формат `summary.md` | Пересобрать по контракту выше |

## Защита от повторов (идемпотентность)

Повторный запуск при уже выкатанной миссии:
- PDF перезаливается (новая версия)
- Email и WhatsApp НЕ отправляются повторно

## ⛔ ГЕЙТ: Запрет на удаление с GDrive

- **КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО** удалять файлы из `gdrive:DariaGalactic/Клиенты/Разборы/`
- **КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО** использовать `rclone sync` (удаляет отсутствующие на источнике) — только `rclone copy`
- **КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО** удалять или перемещать папки клиентов на GDrive
- Файлы на GDrive подтянуты в личные кабинеты клиентов — удаление = клиент теряет доступ
- Перезапись допускается ТОЛЬКО при обновлении разбора (новая версия PDF/картинки)
- Перед любой операцией с GDrive — проверить, что команда = `rclone copy`, НЕ `rclone sync`
