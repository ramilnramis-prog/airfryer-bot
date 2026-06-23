# Airfryer Content API (v1) — для n8n

FastAPI-сервис, отдельный от Telegram-бота. Запуск: `uvicorn api.main:app`.

## Структура
```
api/
├── __init__.py
├── main.py            # FastAPI, роуты, статика
├── config.py          # пути и env
├── auth.py            # проверка X-API-Key -> 401
├── db.py              # SQLite очередь задач (data/jobs.db)
├── posts.py           # recipes.json -> готовый telegram-пост
├── pdfgen.py          # PDF из markdown / из рецептов (DejaVu, кириллица)
├── jobs.py            # фоновые задачи + job_id (uuid4)
├── requirements.txt
├── Dockerfile         # build context = корень репо
└── README.md
data/                  # создаётся в рантайме (Railway Volume): jobs.db, gen/*.pdf
```

## ENV variables
| Переменная | Обяз. | Назначение |
|------------|-------|------------|
| `API_KEY` | да | секрет для заголовка `X-API-Key` |
| `DATA_DIR` | реком. | путь для jobs.db и PDF; на Railway = точка монтирования Volume, напр. `/data` |
| `BASE_URL` | реком. | публичный URL сервиса (для file_url/image_url). Если пусто — берётся из запроса |
| `PDF_FONT` | нет | путь к TTF (по умолч. DejaVuSans, ставится в Docker) |
| `PDF_FONT_BOLD` | нет | путь к bold TTF |
| `OZON_ARTIKUL` | нет | по умолч. `1931921872` |
| `TG_CHANNEL` | нет | название канала для подписей |
| `PORT` | — | отдаёт Railway автоматически |

## curl-примеры (замени HOST и KEY)
```bash
# health
curl https://HOST/health

# prepare-telegram-post (recipe_id 1..50)
curl -X POST https://HOST/prepare-telegram-post \
  -H "X-API-Key: KEY" -H "Content-Type: application/json" \
  -d '{"recipe_id": 1}'

# generate-pdf из рецептов
curl -X POST https://HOST/generate-pdf \
  -H "X-API-Key: KEY" -H "Content-Type: application/json" \
  -d '{"source":"recipes","recipe_ids":[1,2,3],"filename":"sbornik.pdf"}'

# generate-pdf из markdown
curl -X POST https://HOST/generate-pdf \
  -H "X-API-Key: KEY" -H "Content-Type: application/json" \
  -d '{"source":"markdown","content":"# Заголовок\n- пункт 1\n- пункт 2","filename":"doc.pdf"}'

# generate-content (заглушка v1)
curl -X POST https://HOST/generate-content \
  -H "X-API-Key: KEY" -H "Content-Type: application/json" \
  -d '{"type":"caption","recipe_id":1,"platform":"reels"}'

# publish-status
curl "https://HOST/publish-status?job_id=JOB_ID" -H "X-API-Key: KEY"

# скачать готовый PDF
curl -O "https://HOST/files/sbornik.pdf"
```

## Railway deployment notes
1. В том же проекте Railway: **New Service → Deploy from GitHub repo** → выбрать `airfryer-bot`
   (тот же репозиторий, что и бот; бот остаётся отдельным сервисом).
2. Settings → **Dockerfile Path** = `api/Dockerfile` (build context = корень репо).
3. Variables: `API_KEY`, `DATA_DIR=/data`, `BASE_URL=https://<этот-сервис>.up.railway.app`.
4. **Volume**: добавить том, mount path `/data` — чтобы jobs.db и PDF переживали редеплой.
5. Settings → Networking → **Generate Domain** (публичный URL для n8n и file_url).
6. Health check путь: `/health`.
7. В n8n: ноды **HTTP Request** на эти роуты + заголовок `X-API-Key`.

## Заметки v1
- `/generate-content` — заглушка (возвращает echo). Реальную генерацию подключим к LLM-API (ключ в env).
- PDF-задачи и generate-content идут фоном (BackgroundTasks); статус опрашивать через `/publish-status`.
- Видео в API v1 не входит (нужен внешний gen-API + хранилище) — см. `API_SPEC.md`.
