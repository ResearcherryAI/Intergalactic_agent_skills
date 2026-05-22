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

## PRE-DELIVERY CHECKLIST (БЛОКИРУЮЩИЙ)

- [ ] `<Имя>_<DDMMYYYY>_миссия.pdf` существует, >500KB (собран из v2 после AI-агента)
- [ ] `<Имя>_<DDMMYYYY>_миссия_v2.md` существует (для новых клиентов с AI-флоу)
- [ ] `benchmark_report.md` существует, score v2 ≥ 0.90
- [ ] `summary.md` существует, frontmatter валиден (3 секции)
- [ ] `Generated_image.png` существует, >100KB
- [ ] Email взят из Sheet (не из памяти)
- [ ] Имя в файле = имя в Sheet
- [ ] Дата в файле = дата в Sheet
- [ ] Статус в Sheet ∈ {«Разбор АИ готов (на проверке у Кайи)», «В разборе у Кайи Каэн»}
- [ ] Получено явное «можно отправлять» от Дарьи в чате

Если хотя бы один пункт не прошёл — СТОП, не запускать.

## Скрипт

```
.cursor/skills/6-delivery/deliver_mission.py
```

Конфиг: `DariaGalactic/config/` — `.env`, `client_secret_*.json`, `gdrive_token.json`, `cabinet_sheet_token.json`.

Если конфиг удалён или машина новая, восстановить runtime-креды из приватного репозитория `https://github.com/ResearcherryAI/Intergalacticcreds.git`. Для delivery нужны только `.env`, `client_secret_*.json`, `gdrive_token.json`, `cabinet_sheet_token.json`; мастер-секреты и admin-drive токены не копировать без отдельной необходимости.

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
rclone copy "<папка_клиента>/Generated_image.png" "gdrive:DariaGalactic/Профайлы клиентов/<имя_папки>/"
rclone copy "<папка_клиента>/<Имя>_миссия.pdf" "gdrive:DariaGalactic/Профайлы клиентов/<имя_папки>/"
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

```powershell
cd "D:\DariaGalactic\Профайлы клиентов"

# 1) Снапшот AI-выхода (raw от агента) — отдельный коммит
git add "<папка_клиента>/<Имя>_<DDMMYYYY>_миссия.md"
git add "<папка_клиента>/karta_*.csv"
git commit -m "[ai-snapshot] <Имя> <DDMMYYYY> — raw разбор от intergalactic-agent"

# 2) Доработка Кайи (v2 + benchmark_report + summary + image)
git add "<папка_клиента>/<Имя>_<DDMMYYYY>_миссия_v2.md"
git add "<папка_клиента>/benchmark_report.md"
git add "<папка_клиента>/summary.md"
git commit -m "[v2-edits] <Имя> <DDMMYYYY> — доработка Кайи, score X.XX"

# 3) Доставка (статус ready, ссылки в Sheet)
git commit --allow-empty -m "[delivery] <Имя> <DDMMYYYY> — миссия выдана клиенту"
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
| R2 upload failed | CF токен / bucket | Проверить `.env` |
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
