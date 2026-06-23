# Dockerfile для API-сервиса. Build context = КОРЕНЬ репозитория (где recipes.json, photos/).
# В Railway: Service -> Settings -> Dockerfile Path = api/Dockerfile
FROM python:3.12-slim

# Шрифты DejaVu для кириллицы в PDF
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Данные, нужные API (из корня репозитория)
COPY recipes.json lead_magnet.md /app/
COPY photos /app/photos
COPY api /app/api

# PORT отдаёт Railway
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
