# Спецификация: pull_client.py + deliver_mission.py

> Полный пайплайн от оплаты клиента до появления разбора в личном кабинете.
> Версия: FIX-28+ (21.05.2026). Поддержка двух продуктов: `mission` и `money_dna`.

---

## Ключевой принцип

Все продукты деплоятся в один и тот же личный кабинет, привязанный к email клиента, независимо от contractId. ContractId используется для различения нескольких покупок одного продукта под одним email (например, клиент купил разбор для себя и для мужа — два contractId, оба в одном ЛК). В `/sales` воркер отдаёт массивы `missions[]` и `moneyDnas[]`, `me.js` рендерит каждый как отдельную карточку-вкладку, но всё внутри одного ЛК.

Оба скрипта (`pull_client.py` и `deliver_mission.py`) уже обновлены с учётом этого (FIX-28):
- поддерживают `--product mission|money_dna`;
- фильтруют строки Google Sheet по ключевым словам продукта;
- pull выбирает запись с учётом `productCode` из KV.

---

## Как работает полная цепочка pull → deliver → ЛК

### Шаг 0. Клиент оплатил (воркер `intergalactic-cabinet`)

После оплаты через LavaTop воркер автоматически:

1. Создаёт подпапку клиента в Google Drive внутри общей папки `GDRIVE_FOLDER_ID`:
   - Имя: `<Имя>_<contract12>_<YYYYMMDD>` (напр. `Гульнара_10c2639cd521_20260518`)
2. Кладёт туда `karta_<short>.csv` (натальная карта, посчитанная на фронте)
3. Сохраняет в KV `missions:<email>` поля: `driveFolderId`, `chartCsvLink`, `chartCsvFileId`, `contractId`, `status: in_review`
4. Пишет строку в Google Sheet (таблица «Покупки»): email, имя, продукт, contractId, дата, телефон
5. Отправляет клиенту email и WA#1/WA#2 с ссылкой на оплату (если split-flow) или сразу WA paid

---

### Шаг 1. `pull_client.py` скачивает CSV локально

Запуск:

```bash
python3 pull_client.py <email> [--contract <contractId>] [--product mission|money_dna]
```

Что делает:

1. Идёт в воркер: `GET /admin/mission?email=…` — получает список всех миссий/money_dna для этого email
2. Выбирает нужную запись по `--contract` или `--product` (или первую активную `in_review`/`awaiting_chart`)
3. Берёт `driveFolderId` из записи (его создал воркер при оплате)
4. Скачивает **всё содержимое** Drive-подпапки клиента в локальную директорию:
   - Путь: `~/Desktop/Producty/4_Intergalactic/DariaGalacticChakra/Профайлы клиентов/<Имя>_<contract12>_<YYYYMMDD>/`
   - Файлы: `karta_<short>.csv` (и любые другие, если уже что-то положили)
5. Если CSV в Drive нет (мобильный iframe прервался) — авто-regen через headless Chromium

**Фолбек**: если у миссии нет `driveFolderId` (legacy/seed), скрипт сам создаёт подпапку и регистрирует её через `POST /admin/mission/drive`.

---

### Шаг 2. Кайя делает разбор + кладёт файлы в локальную папку

В ту же локальную папку (`Профайлы клиентов/<Имя>_<contract12>_<YYYYMMDD>/`) оператор кладёт:

- `<что-то>_миссия.pdf` — полный разбор
- `Generated_image.png` — обложка-визуализация
- `summary.md` — выжимка (frontmatter + 3 секции: Ваш дар / Ваш вызов / Что делать)

---

### Шаг 3. `deliver_mission.py` отправляет разбор в систему

Запуск:

```bash
python3 deliver_mission.py [--product mission|money_dna] <email> <путь_к_папке_клиента>
```

Что делает по порядку:

1. **Лукап в Sheet** — находит строку по email и product-фильтру (mission / money_dna), берёт `contractId`, `sheetRow`, `buyerName`, `phone`
2. **Проверка оператора** — показывает данные из Sheet и требует подтверждение «это правильный клиент?» (защита от отправки не тому)
3. **Находит/создаёт подпапку клиента в Drive** — `<Имя>_<contract12>_<YYYYMMDD>` внутри `GDRIVE_FOLDER_ID`
4. **Загрузка PDF в Drive** — `mission_<email-slug>_<timestamp>.pdf` в папку клиента, с public-share (anyone with link)
5. **Загрузка обложки (PNG)** — в ту же папку Drive
6. **Записывает ссылку на папку в Sheet col O** — Кайя видит ссылку прямо в таблице
7. **Парсит `summary.md` → HTML** — три секции-тезиса для inline-preview в ЛК
8. **Сжимает обложку в WebP** (1200px, quality 78) для кабинета
9. **Загружает cover.webp и summary.html в Cloudflare R2** — по ключам `mission/<contract12>/cover.webp` и `mission/<contract12>/summary.html`
10. **Дёргает воркер `POST /admin/mission`** с payload:

```json
{
  "email": "...",
  "status": "ready",
  "driveLink": "https://drive.google.com/...",
  "fileName": "mission_..._2026-05-21_10-00.pdf",
  "driveImageLink": "...",
  "contractId": "...",
  "inlinePreview": true,
  "coverKey": "mission/<contract12>/cover.webp",
  "summaryKey": "mission/<contract12>/summary.html",
  "civilization": "Сириус",
  "headline": "..."
}
```

---

### Шаг 4. Что делает воркер (`/admin/mission`) при получении payload

1. Обновляет KV `missions:<email>` — status → `ready`, пишет `driveLink`, `coverKey`, `summaryKey`, `civilization`, `headline`
2. Обновляет Google Sheet col G → «Готово. Разбор выдан клиенту»
3. Отправляет email клиенту «Ваш разбор готов» (через Resend)
4. Отправляет WhatsApp клиенту «Анализ миссии звёздной души готов, ваш ЛК: ...» (через Green API, используя номер из `missions:<email>.phone`)

---

### Шаг 5. Как это встраивается в личный кабинет клиента

Клиент заходит на `intergalactic-astrology.com/me/` (magic-link с токеном из email/WA).

`me.js` вызывает `GET /sales?email=...&token=...` — воркер возвращает:

```json
{
  "missions": [{
    "status": "ready",
    "driveLink": "https://drive.google.com/.../mission_xxx.pdf",
    "inlinePreview": true,
    "coverKey": "mission/<contract12>/cover.webp",
    "summaryKey": "mission/<contract12>/summary.html",
    "civilization": "Сириус",
    "headline": "Посланник галактического сознания",
    "productCode": "mission",
    "buyerName": "Гульнара"
  }],
  "moneyDnas": [{
    "status": "in_review",
    "productCode": "money_dna",
    "buyerName": "Гульнара"
  }]
}
```

`me.js` рендерит карточку миссии:

- Если `inlinePreview = true`: показывает обложку (WebP из R2), заголовок с цивилизацией, три секции-тезиса (HTML из R2), кнопку «Скачать полный PDF» (ссылка на Drive)
- Если `inlinePreview` нет (legacy): просто кнопка «Открыть разбор →» по `driveLink`
- Если `status = in_review`: показывает «Разбор будет готов в течение 24–36 часов» (для mission) или «24–48 часов» (для money_dna)

Для `money_dna` — всё то же самое, отдельная карточка-вкладка «`<Имя>: Архитектура денег`», фильтрация по `productCode`.

---

## Резюме в одной схеме

```
Оплата (LavaTop)
  ↓
Воркер → Drive/<Имя>_<contract12>_<date>/karta_<short>.csv
  ↓                                       + KV missions:<email>
  ↓                                       + Sheet row
pull_client.py <email>
  ↓
Локально: Профайлы клиентов/<Имя>_<contract12>_<date>/karta_*.csv
  ↓
Кайя делает разбор → кладёт PDF + PNG + summary.md
  ↓
deliver_mission.py <email> <папка>
  ↓
Drive: PDF + PNG в ту же подпапку клиента
R2: cover.webp + summary.html (для inline ЛК)
Sheet: col O = ссылка на папку, col G = «Готово»
  ↓
POST /admin/mission → KV status=ready
  ↓
Email клиенту + WhatsApp клиенту
  ↓
Клиент открывает /me/ → видит карточку с inline-preview
```

---

## Конфигурация (DariaGalactic/config/)

| Файл | Назначение |
|---|---|
| `.env` | `WORKER_URL`, `ADMIN_SECRET`, `GDRIVE_FOLDER_ID`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_R2_BUCKET`, `CLOUDFLARE_R2_TOKEN`, `SHEET_ID` |
| `client_secret_*.json` | OAuth Desktop app из Google Cloud Console |
| `gdrive_token.json` | Авто-создаётся после первой авторизации (scope `drive` — полный). Переавторизация: `python .cursor/skills/6-delivery/_reauth.py` |
| `cabinet_sheet_token.json` | Sheets scope токен для записи в таблицу |

**Важно**: `gdrive_token.json` должен быть выписан со scope `drive` (полный), НЕ `drive.file`. Scope `drive.file` не показывает файлы, созданные другими приложениями (n8n), что приводит к инцидентам с мисдоставкой.

---

## Зависимости (установка один раз)

```bash
python3 -m pip install --upgrade \
  google-api-python-client google-auth-httplib2 google-auth-oauthlib \
  requests python-dotenv Pillow markdown
```

Для авто-regen CSV (headless):

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

---

## FAQ

**Q: Если у клиента 2 покупки mission (для себя и для мужа) — как различить?**
A: Каждая покупка имеет свой `contractId`. Pull и deliver работают по `--contract <id>`. В ЛК клиента обе отображаются как отдельные вкладки.

**Q: Что если у клиента mission И money_dna?**
A: Это два разных массива в ответе `/sales`: `missions[]` и `moneyDnas[]`. Pull/deliver различают через `--product mission|money_dna`. В ЛК — две отдельные карточки с разными заголовками.

**Q: Можно запускать deliver повторно?**
A: Да, идемпотентно. При повторной отправке PDF перезаливается, но письмо/WA «разбор готов» НЕ дублируется (воркер проверяет previousStatus).

**Q: Что если deliver отправить не тому клиенту?**
A: Скрипт ОБЯЗАТЕЛЬНО показывает данные из Sheet перед отправкой и требует подтверждение. Пропустить можно только флагом `--yes` (для автоматизации). Было 3 инцидента — теперь защита на уровне кода.
