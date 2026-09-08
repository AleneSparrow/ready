# Flibusta Reader — Telegram-бот с читалкой

Личный бот для поиска и чтения книг из библиотеки на Google Drive. Поиск — в чате
с ботом, чтение — в Telegram Mini App, без скачивания файла.

## Как это устроено

- `bot/` — Python-сервис (FastAPI + aiogram): бот, API, отдаёт Mini App
- `webapp/index.html` — сама читалка (Telegram Mini App)
- Каталог книг (`flibusta_catalog.db`) и сами архивы `.7z` лежат на Google Drive,
  сервис обращается к ним через `rclone`

## Локальный запуск (для разработки)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # и заполнить значения
python3 -m bot.main
```

Для локального запуска rclone должен быть уже настроен на этом компьютере
(`rclone listremotes` должен показывать `gdrive:`) — тогда `RCLONE_CONF_BASE64`
в `.env` можно оставить пустым.

## Что нужно сделать вручную перед деплоем

### 1. Создать бота в Telegram

Написать **@BotFather** → `/newbot` → следовать инструкциям → он даст токен вида
`123456:ABC-DEF...`. Сохрани его — понадобится на шаге деплоя.

### 2. Доступ к Google Drive с сервера

Два варианта (выбери один):

**Вариант A — переиспользовать текущий rclone (проще, быстрее)**

На этом Mac, где уже настроен `rclone`, выполнить:

```bash
base64 -i ~/.config/rclone/rclone.conf | pbcopy
```

Это скопирует содержимое в буфer обмена — вставишь как значение переменной
`RCLONE_CONF_BASE64` в Railway (шаг ниже). Имей в виду: это токен с полным
доступом к твоему личному Google Drive.

**Вариант B — Service Account (безопаснее, но больше шагов)**

1. [console.cloud.google.com](https://console.cloud.google.com) → создать проект
2. APIs & Services → Library → включить **Google Drive API**
3. APIs & Services → Credentials → Create Credentials → **Service Account**
4. Открыть созданный service account → Keys → Add Key → JSON → скачается файл
5. В Google Drive расшарить (Share) обе папки — с библиотекой и с
   `flibusta_catalog` — на email из JSON-файла (вида
   `xxx@yyy.iam.gserviceaccount.com`), с правом "Viewer"
6. Код для чтения через Service Account придётся добавить отдельно
   (`google-api-python-client` вместо текущего `rclone`-обёртки в `gdrive.py`) —
   скажи, если выбираешь этот путь, допишу.

### 3. Деплой на Railway

1. Создать новый проект в Railway, подключить этот репозиторий (или задеплоить
   через Railway CLI из этой папки)
2. Добавить **Volume**, примонтировать в `/data` (там будет храниться каталог и
   кэш скачанных архивов)
3. В Variables сервиса добавить (значения — руками, через веб-интерфейс Railway):
   - `TELEGRAM_BOT_TOKEN` — токен от BotFather
   - `WEBAPP_BASE_URL` — публичный домен сервиса, Railway выдаёт после первого
     деплоя (Settings → Networking → Generate Domain), вида
     `https://flibusta-reader-production.up.railway.app`
   - `GDRIVE_LIBRARY_FOLDER_ID` = `14s1PKz7GjqsNjr6kzknV7-0hia6JmN0Z`
   - `GDRIVE_CATALOG_FOLDER_ID` = `18g1jRjYT_DXBV5ZBBCQ8D7f20WMACbrx`
   - `RCLONE_CONF_BASE64` — если выбрала вариант A (см. выше)
4. Деплой — при первом старте контейнер сам скачает `flibusta_catalog.db` с
   Drive в volume (займёт минуту, дальше уже не будет перекачивать)

### 4. Проверка

Написать своему боту в Telegram любое название книги — должны прийти кнопки
с результатами, при нажатии открывается читалка.

## Известные ограничения (MVP)

- Некоторые эпабы без части ресурсов (например, картинок) — читалка просто не
  показывает изображение, текст остаётся читаемым
- Скачивание архива при первом открытии книги из него может занять несколько
  секунд (архивы до ~350 МБ) — дальше кешируется на volume, повторное открытие
  быстрое
- Форматы кроме fb2/epub (если попадутся в каталоге) пока не поддержаны
