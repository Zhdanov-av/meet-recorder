import os
import sys
import time
import traceback
from pathlib import Path

def get_logs_dir() -> Path:
    """Папка логов в корне проекта"""
    base_dir = Path(__file__).resolve().parent.parent / "logs"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir

LOG_FILE_PATH = get_logs_dir() / "app.log"

class Logger:
    def __init__(self, log_path: Path = LOG_FILE_PATH):
        self.log_path = log_path
        self._ensure_log_file()

    def _ensure_log_file(self):
        if not self.log_path.exists():
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write(f"=== Meet Recorder Log Started: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")

    def _write(self, level: str, msg: str):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {msg}\n"
        
        # Вывод в консоль если доступен
        if sys.stdout and hasattr(sys.stdout, "write"):
            try:
                sys.stdout.write(log_line)
                sys.stdout.flush()
            except Exception:
                pass

        # Дозапись в app.log
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(log_line)
                f.flush()
        except Exception as e:
            pass

    def info(self, msg: str):
        self._write("INFO", msg)

    def warning(self, msg: str):
        self._write("WARNING", msg)

    def error(self, msg: str, exc: Exception = None):
        if exc:
            err_details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            self._write("ERROR", f"{msg}\n{err_details}")
        else:
            self._write("ERROR", msg)

logger = Logger()

def setup_exception_logging():
    """Перехватывает любые необработанные исключения Python и записывает их в app.log"""
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        logger.error(f"Необработанное исключение системы:\n{err_msg}")

    sys.excepthook = handle_exception
