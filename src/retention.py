import time
from pathlib import Path
from src.config import get_base_recordings_dir, config

def cleanup_old_media(days: int = None):
    """
    Рекурсивно удаляет аудио и видео файлы из папки recordings и ее подпапок проектов,
    возраст которых превышает заданное количество дней (7 дней).
    .md файлы не затрагиваются, так как они находятся в папках проектов.
    """
    if days is None:
        days = config.get("retention_days", 7)

    base_dir = get_base_recordings_dir()
    cutoff_time = time.time() - (days * 86400)
    deleted_count = 0

    if not base_dir.exists():
        return

    # Обходим все файлы во всех подпапках recordings/
    for media_file in base_dir.rglob("*"):
        if media_file.is_file() and media_file.suffix.lower() in [".wav", ".mp3", ".mp4", ".mkv", ".avi"]:
            try:
                file_mtime = media_file.stat().st_mtime
                if file_mtime < cutoff_time:
                    media_file.unlink()
                    deleted_count += 1
                    print(f"[Retention] Удален устаревший файл записи: {media_file.relative_to(base_dir)}")
            except Exception as e:
                print(f"[Retention] Ошибка удаления файла {media_file.name}: {e}")

    if deleted_count > 0:
        print(f"[Retention] Автоочистка завершена. Удалено устаревших записей: {deleted_count}")
