"""Конфигурация API: пути, env-переменные. Папки создаются при импорте."""
import os
from pathlib import Path

# Корень репозитория (где лежат recipes.json, lead_magnet.md, photos/)
ROOT = Path(__file__).resolve().parent.parent

RECIPES_FILE = ROOT / "recipes.json"
LEAD_MAGNET = ROOT / "lead_magnet.md"
PHOTOS_DIR = ROOT / "photos"

# Хранилище генерируемых файлов (на Railway монтировать Volume и задать DATA_DIR=/data)
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
GEN_DIR = DATA_DIR / "gen"
DB_PATH = DATA_DIR / "jobs.db"

# Секрет для X-API-Key (обязателен)
API_KEY = os.environ.get("API_KEY", "")

# Публичный URL сервиса для сборки file_url/image_url. Если пусто — берём из запроса.
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

# Авто-применение миграций реестра на старте API. По умолчанию ВЫКЛ, чтобы prod-база
# не мигрировала случайно при деплое кода. Включать ЯВНО: REGISTRY_AUTO_MIGRATE=1
# (локально/в тестах) либо запускать миграцию командой `python -m api.registry_db`.
REGISTRY_AUTO_MIGRATE = os.environ.get("REGISTRY_AUTO_MIGRATE", "").strip().lower() in (
    "1", "true", "yes", "on")

# Шрифты для PDF с кириллицей (ставятся в Docker через fonts-dejavu-core)
PDF_FONT = os.environ.get("PDF_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
PDF_FONT_BOLD = os.environ.get("PDF_FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

# Для CTA в подписях
OZON_ARTIKUL = os.environ.get("OZON_ARTIKUL", "1931921872")
TG_CHANNEL = os.environ.get("TG_CHANNEL", "Умная готовка")

# Гарантируем наличие папок (нужно до монтирования StaticFiles)
GEN_DIR.mkdir(parents=True, exist_ok=True)
