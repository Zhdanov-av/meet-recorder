import os
import sys
import json
import winreg
from pathlib import Path

APP_VERSION = "1.0.0"
APP_NAME = "MeetRecorder"
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULT_CONFIG = {
    "projects": {},  # {"Имя Проекта": "C:\\Путь\\К\\Папке"}
    "autostart": False,  # По умолчанию выключено
    "start_minimized": False,  # По умолчанию выключено
    "hotkey": "<ctrl>+<alt>+z",
    "play_sound_signals": True,
    "show_floating_widget": True,
    "selected_mic": "",
    "selected_speaker": "",
    "compute_device": "cpu",
    "whisper_model": "medium",
    "retention_days": 7,
    "first_run": True,
    "last_project": "",
    "github_repo": "Zhdanov-av/meet-recorder"  # Репозиторий для проверки обновлений
}

def get_install_root() -> Path:
    """Возвращает корневую директорию установленной программы"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

def get_app_dir() -> Path:
    """Возвращает путь к директории хранения настроек и кэша в AppData"""
    app_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MeetRecorder"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir

def get_base_recordings_dir() -> Path:
    """
    Папка 'recordings' внутри директории программы.
    Если она недоступна для записи (например, системные ограничения),
    выполняется fallback на AppData/MeetRecorder/recordings.
    """
    root_recordings = get_install_root() / "recordings"
    try:
        root_recordings.mkdir(parents=True, exist_ok=True)
        # Проверяем возможность записи
        test_file = root_recordings / ".write_test"
        test_file.touch(exist_ok=True)
        test_file.unlink(missing_ok=True)
        return root_recordings
    except Exception:
        fallback_recordings = get_app_dir() / "recordings"
        fallback_recordings.mkdir(parents=True, exist_ok=True)
        return fallback_recordings

def get_project_recordings_dir(project_name: str) -> Path:
    """Подпапка 'recordings/<ИмяПроекта>' конкретного проекта"""
    safe_name = "".join(c for c in project_name if c.isalnum() or c in (" ", "_", "-")).strip()
    if not safe_name:
        safe_name = "Default"
    proj_dir = get_base_recordings_dir() / safe_name
    proj_dir.mkdir(parents=True, exist_ok=True)
    return proj_dir

def get_cache_dir() -> Path:
    return get_base_recordings_dir()

class ConfigManager:
    def __init__(self):
        # Настройки хранятся в AppData, чтобы гарантированно сохраняться при любых обновлениях бинарников
        self.config_path = get_app_dir() / "config.json"
        self.data = DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    self.data.update(loaded)
            except Exception as e:
                print(f"[Config] Ошибка чтения конфига: {e}")
        else:
            self.save()

    def save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Config] Ошибка сохранения конфига: {e}")

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def add_project(self, name: str, folder_path: str):
        self.data["projects"][name] = folder_path
        self.save()
        get_project_recordings_dir(name)

    def remove_project(self, name: str):
        if name in self.data["projects"]:
            del self.data["projects"][name]
            self.save()

    def update_autostart_registry(self, enable: bool):
        """Включает или выключает автозапуск приложения в реестре Windows"""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_ALL_ACCESS)
            if enable:
                if getattr(sys, "frozen", False):
                    # Если собрано в exe (MeetRecorder.exe)
                    exe_path = str(Path(sys.executable).resolve())
                    cmd = f'"{exe_path}" --autostart'
                else:
                    # Если запуск из скрипта Python
                    py_dir = Path(sys.executable).parent
                    pythonw_exe = py_dir / "pythonw.exe"
                    if not pythonw_exe.exists():
                        pythonw_exe = sys.executable
                    script_path = str(Path(__file__).resolve().parent.parent / "main.py")
                    cmd = f'"{pythonw_exe}" "{script_path}" --autostart'

                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                print("[Registry] Автозапуск включен в реестре")
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    print("[Registry] Автозапуск удален из реестра")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[Registry] Ошибка обновления автозапуска в реестре: {e}")

config = ConfigManager()
