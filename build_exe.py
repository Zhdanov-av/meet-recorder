import os
import sys
import shutil
import subprocess
from pathlib import Path

def build():
    root_dir = Path(__file__).resolve().parent
    dist_dir = root_dir / "dist"
    build_dir = root_dir / "build"

    print("=== Начало сборки Meet Recorder через PyInstaller ===")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=MeetRecorder",
        "--onedir",
        "--noconsole",
        "--noconfirm",
        "--clean",
        f"--icon={str(root_dir / 'assets' / 'icon.ico')}",
        f"--add-data={str(root_dir / 'assets')};assets",
        "--collect-all=soundcard",
        "--collect-all=faster_whisper",
        "--collect-all=ctranslate2",
        "--hidden-import=pynput.keyboard._win32",
        "--hidden-import=PySide6.QtCore",
        "--hidden-import=PySide6.QtGui",
        "--hidden-import=PySide6.QtWidgets",
        str(root_dir / "main.py")
    ]

    print(f"Выполняется команда: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=str(root_dir))

    if res.returncode == 0:
        print("\n✅ Сборка успешно завершена!")
        print(f"Папка с готовым приложением: {dist_dir / 'MeetRecorder'}")
        
        # Создаем папку recordings внутри собранного пакета
        rec_dir = dist_dir / "MeetRecorder" / "recordings"
        rec_dir.mkdir(parents=True, exist_ok=True)
        print(f"Папка recordings подготовлена: {rec_dir}")
    else:
        print(f"\n❌ Ошибка сборки! Код возврата: {res.returncode}")

if __name__ == "__main__":
    build()
