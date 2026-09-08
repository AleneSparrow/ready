"""Подготовка окружения при старте контейнера: rclone.conf и каталог."""
import base64
import os
import subprocess

from . import config


def setup_rclone_config() -> None:
    b64 = os.environ.get("RCLONE_CONF_BASE64")
    if not b64:
        return  # локальная разработка — rclone.conf уже есть у пользователя
    conf_dir = os.path.expanduser("~/.config/rclone")
    os.makedirs(conf_dir, exist_ok=True)
    conf_path = os.path.join(conf_dir, "rclone.conf")
    if not os.path.exists(conf_path):
        with open(conf_path, "wb") as f:
            f.write(base64.b64decode(b64))


def ensure_catalog_db() -> None:
    if os.path.exists(config.CATALOG_DB_PATH):
        return
    if not config.GDRIVE_CATALOG_FOLDER_ID:
        raise RuntimeError(
            "flibusta_catalog.db не найден локально и GDRIVE_CATALOG_FOLDER_ID не задан"
        )
    os.makedirs(os.path.dirname(config.CATALOG_DB_PATH) or ".", exist_ok=True)
    subprocess.run(
        [
            "rclone",
            "copyto",
            "gdrive:flibusta_catalog.db",
            config.CATALOG_DB_PATH,
            f"--drive-root-folder-id={config.GDRIVE_CATALOG_FOLDER_ID}",
        ],
        check=True,
    )


def run() -> None:
    setup_rclone_config()
    ensure_catalog_db()
