"""Конфигурация из переменных окружения. Ничего секретного тут не хранится —
только чтение того, что задано в Railway (или в .env локально)."""
import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
WEBAPP_BASE_URL = os.environ.get("WEBAPP_BASE_URL", "http://localhost:8000")

# Папка с самой библиотекой (архивы .7z) на Google Drive
GDRIVE_LIBRARY_FOLDER_ID = os.environ.get("GDRIVE_LIBRARY_FOLDER_ID", "")
# Папка с flibusta_catalog.db (на личном Drive Алёны)
GDRIVE_CATALOG_FOLDER_ID = os.environ.get("GDRIVE_CATALOG_FOLDER_ID", "")

CACHE_DIR = os.environ.get("CACHE_DIR", "./data/cache")
CATALOG_DB_PATH = os.environ.get("CATALOG_DB_PATH", "./data/flibusta_catalog.db")

PORT = int(os.environ.get("PORT", "8000"))
