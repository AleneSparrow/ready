"""Доступ к Google Drive через уже настроенный rclone (remote "gdrive").

На проде rclone.conf кладётся из переменной окружения RCLONE_CONF_BASE64
(см. bootstrap.py) — это переиспользование личного OAuth-токена Алёны.
Более безопасный вариант (Service Account с доступом только к нужным папкам)
описан в README — можно переключить позже, не трогая остальной код: для этого
достаточно заменить реализацию download_file на google-api-python-client.
"""
import os
import subprocess

REMOTE = "gdrive"


def download_file(name: str, local_path: str, folder_id: str) -> None:
    """Скачивает файл `name` из папки `folder_id` на Google Drive в local_path."""
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    cmd = [
        "rclone",
        "copyto",
        f"{REMOTE}:{name}",
        local_path,
        f"--drive-root-folder-id={folder_id}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"rclone copyto failed for {name}: {result.stderr}")
