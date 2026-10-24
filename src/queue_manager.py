import os
import json
import time
import queue
import threading
from pathlib import Path
from PySide6.QtCore import QObject, Signal

from src.logger import logger
from src.transcription import transcriber

def get_history_file() -> Path:
    base_dir = Path(__file__).resolve().parent.parent / "logs"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "history.json"

class TranscriptionQueueManager(QObject):
    task_added = Signal(dict)
    task_updated = Signal(dict)
    queue_changed = Signal(int, bool)  # queued_count, is_processing

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history_file = get_history_file()
        self.history = []
        self._load_history()

        self.task_queue = queue.Queue()
        self.is_processing = False
        self.current_task_id = None

        # Запуск фонового потока обработки очереди
        self.worker_thread = threading.Thread(target=self._process_queue_loop, daemon=True)
        self.worker_thread.start()

    def _load_history(self):
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception as e:
                logger.error("Ошибка чтения истории транскрибаций", exc=e)
                self.history = []

    def _save_history(self):
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Ошибка сохранения истории транскрибаций", exc=e)

    def add_task(self, audio_path: Path, project_name: str, meeting_title: str) -> dict:
        timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")
        task_id = f"task_{int(time.time() * 1000)}"

        task = {
            "id": task_id,
            "created_at": timestamp_str,
            "audio_path": str(audio_path),
            "audio_name": audio_path.name,
            "project_name": project_name,
            "meeting_title": meeting_title or f"Встреча_{time.strftime('%H-%M')}",
            "status": "⏳ В очереди",
            "result_md": "",
            "error": ""
        }

        self.history.insert(0, task)
        self._save_history()

        self.task_added.emit(task)
        self.task_queue.put(task)

        queued_count = self.task_queue.qsize()
        self.queue_changed.emit(queued_count, self.is_processing)

        logger.info(f"Добавлена задача в очередь транскрибации: '{task['meeting_title']}' (Проект: {project_name})")
        return task

    def _process_queue_loop(self):
        while True:
            task = self.task_queue.get()
            if task is None:
                break

            self.is_processing = True
            self.current_task_id = task["id"]
            
            # Обновляем статус задачи на "В обработке"
            self._update_task_status(task["id"], "🔄 В обработке...")
            self.queue_changed.emit(self.task_queue.qsize(), True)

            audio_path = Path(task["audio_path"])
            project_name = task["project_name"]
            title = task["meeting_title"]

            try:
                logger.info(f"[QueueManager] Обработка задачи {task['id']} ({audio_path.name})...")
                output_md = transcriber.transcribe_and_save(audio_path, project_name, title)
                
                self._update_task_status(
                    task["id"],
                    "✅ Завершено",
                    result_md=str(output_md)
                )
                logger.info(f"[QueueManager] Задача {task['id']} успешно завершена -> {output_md}")
            except Exception as e:
                logger.error(f"[QueueManager] Ошибка обработки задачи {task['id']}", exc=e)
                self._update_task_status(
                    task["id"],
                    "❌ Ошибка",
                    error=str(e)
                )

            self.is_processing = False
            self.current_task_id = None
            self.task_queue.task_done()
            self.queue_changed.emit(self.task_queue.qsize(), False)

    def _update_task_status(self, task_id: str, status: str, result_md: str = "", error: str = ""):
        for t in self.history:
            if t["id"] == task_id:
                t["status"] = status
                if result_md:
                    t["result_md"] = result_md
                if error:
                    t["error"] = error
                self._save_history()
                self.task_updated.emit(t)
                break

    def get_all_tasks(self):
        return list(self.history)

queue_manager = TranscriptionQueueManager()
