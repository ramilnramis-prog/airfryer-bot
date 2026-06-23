# API для интеграции с n8n — спецификация

## Текущее состояние (факт)
- `bot.py` — Telegram-бот в режиме **long-polling**, БЕЗ веб-сервера и HTTP-эндпоинтов.
  Крутится на Railway как worker.
- Данные: `recipes.json` (50 рецептов, структурировано), `lead_magnet.md`,
  фото `photos/*.jpg`. Видео — пока только локально (`Загрузки`), на сервере НЕТ.
- Нет: API, очереди задач, job_id, секрета вебхука, генерации PDF.

## Решение
Добавляем **отдельный сервис `api/`** (FastAPI, тот же Python) на Railway —
второй сервис в проекте, с публичным URL. Бот остаётся отдельным модулем (не трогаем),
общий код (recipes, форматирование поста) выносим в общий модуль.

```
n8n  --HTTPS+secret-->  FastAPI (Railway)  --->  задачи (job_id) --> файлы (Volume/S3)
                                  |                                    |
                          recipes.json / lead_magnet.md         /files/<name> (file_url)
                                  |
                          (опц.) дёргает бота / LLM / gen-API
```

## Аутентификация
Каждый запрос: заголовок `X-API-Key: <SECRET>` (хранится в Railway Variables).
Нет/неверный ключ → `401`.

## Модель задачи
`job_id` = uuid4. Статусы: `queued → processing → ready | failed`.
Хранение: SQLite (`data/jobs.db`) — переживает рестарт. Логируем job_id в stdout.
Долгие задачи (PDF, генерация) — фоном; n8n опрашивает `/publish-status?job_id=`.

## Эндпоинты

### GET /health
→ `200 {"status":"ok","version":"1.0","uptime_sec":123}`

### POST /prepare-telegram-post
in: `{"recipe_id": 5}` или `{"recipe": {...}}`
→ `200 {"status":"ready","caption":"<готовый текст HTML>","image_url":"https://.../photos/05.jpg","parse_mode":"HTML","metadata":{"category":"Курица","title":"..."}}`
(синхронно — это просто форматирование из recipes.json)

### POST /generate-pdf
in: `{"source":"markdown","content":"# ...","filename":"lead.pdf"}`
или `{"source":"recipes","recipe_ids":[1,2,3],"filename":"sbornik.pdf"}`
→ `202 {"job_id":"...","status":"queued"}`
готово (через /publish-status): `{"status":"ready","file_path":"data/gen/lead.pdf","file_url":"https://.../files/lead.pdf"}`
(PDF собирается на сервере: markdown→HTML→PDF, библиотека weasyprint/reportlab)

### POST /generate-content
in: `{"type":"caption|article|hooks","topic":"...","platform":"reels|dzen","recipe_id":5}`
→ `202 {"job_id":"...","status":"queued"}`
готово: `{"status":"ready","result":{"title":"...","caption":"...","cta":"...","hashtags":[...]}}`
⚠️ Текст генерит LLM-API (нужен ключ, напр. OpenAI/Claude) — провязываем в env.

### GET /publish-status?job_id=...
→ `{"job_id":"...","status":"queued|processing|ready|failed","result":{...},"error":null}`

## Файлы (важно про хранилище)
- Статика (фото) — в репозитории/контейнере, отдаём `/files/photos/NN.jpg`.
- Новые сгенерированные (PDF и т.п.) — в папку `data/gen/`.
- ⚠️ Railway-контейнер ЭФЕМЕРНЫЙ: при деплое стирается. Для постоянного `file_url`
  нужен **Railway Volume** (монтируем `/data`) или внешний **S3** (S3/Yandex Object Storage).

## Видео — честно
Готовые видео сейчас не на сервере. Эндпоинт `/generate-video` потребует внешний
gen-API (Higgsfield REST / др.) + хранилище. Это отдельный этап; на старте видео
лучше держать в SMMplanner-очереди, а через API гнать текст/PDF/telegram-посты.

## Что нужно для запуска
1. Создать сервис `api/` (FastAPI) — могу написать каркас со всеми эндпоинтами.
2. Railway: второй сервис из того же репо, env: `API_KEY`, (опц.) `OPENAI_API_KEY`, S3-ключи.
3. Подключить Railway Volume (`/data`) для постоянных файлов.
4. В n8n: HTTP Request ноды на эти эндпоинты + заголовок `X-API-Key`.
