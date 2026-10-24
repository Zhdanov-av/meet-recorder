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

    media_extensions = [".wav", ".mp3", ".mp4", ".mkv", ".avi"]

    # 1. Обходим все файлы во всех подпапках recordings/
    for media_file in base_dir.rglob("*"):
        if media_file.is_file() and media_file.suffix.lower() in media_extensions:
            try:
                if media_file.stat().st_mtime < cutoff_time:
                    media_file.unlink()
                    deleted_count += 1
                    print(f"[Retention] Удален устаревший файл записи: {media_file.name}")
            except Exception as e:
                print(f"[Retention] Ошибка удаления файла {media_file.name}: {e}")

    # 2. Обходим папки recordings внутри настроенных проектов
    projects = config.get("projects", {})
    for proj_name, proj_folder in projects.items():
        if proj_folder:
            p_rec = Path(proj_folder) / "recordings"
            if p_rec.exists():
                for media_file in p_rec.glob("*"):
                    if media_file.is_file() and media_file.suffix.lower() in media_extensions:
                        try:
                            if media_file.stat().st_mtime < cutoff_time:
                                media_file.unlink()
                                deleted_count += 1
                                print(f"[Retention] Удален устаревший файл проекта '{proj_name}': {media_file.name}")
                        except Exception as e:
                            print(f"[Retention] Ошибка удаления файла проекта {media_file.name}: {e}")

    if deleted_count > 0:
        print(f"[Retention] Автоочистка завершена. Удалено устаревших записей: {deleted_count}")
