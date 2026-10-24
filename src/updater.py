import os
import sys
import json
import urllib.request
import subprocess
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QThread
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QTextEdit, QHBoxLayout, QProgressBar
from PySide6.QtGui import QFont
from src.config import config, APP_VERSION
from src.logger import logger

def parse_version_tuple(v_str: str):
    """Преобразует строку версии 'v1.2.3' в кортеж чисел (1, 2, 3)"""
    clean = v_str.lower().lstrip("v").strip()
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    return tuple(parts)

class UpdateCheckerThread(QThread):
    check_finished = Signal(bool, str, str, str)  # has_update, latest_version, changelog, download_url
    check_failed = Signal(str)

    def __init__(self, repo: str = None, parent=None):
        super().__init__(parent)
        self.repo = repo or config.get("github_repo", "your-username/meet_recording")

    def run(self):
        url = f"https://api.github.com/repos/{self.repo}/releases/latest"
        headers = {
            "User-Agent": "MeetRecorder-Updater",
            "Accept": "application/vnd.github.v3+json"
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            tag_name = data.get("tag_name", "")
            changelog = data.get("body", "Описание изменений отсутствует.")
            latest_tuple = parse_version_tuple(tag_name)
            current_tuple = parse_version_tuple(APP_VERSION)

            has_update = latest_tuple > current_tuple

            download_url = ""
            # Ищем ассет инсталлятора среди файлов релиза
            for asset in data.get("assets", []):
                asset_name = asset.get("name", "").lower()
                if asset_name.endswith(".exe") or asset_name.endswith(".zip"):
                    download_url = asset.get("browser_download_url", "")
                    break

            if not download_url and data.get("html_url"):
                download_url = data.get("html_url")

            self.check_finished.emit(has_update, tag_name, changelog, download_url)

        except Exception as e:
            logger.warning(f"[Updater] Не удалось проверить обновления на GitHub: {e}")
            self.check_failed.emit(str(e))

class UpdateDownloadThread(QThread):
    progress = Signal(int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, download_url: str, parent=None):
        super().__init__(parent)
        self.download_url = download_url

    def run(self):
        temp_dir = Path(os.environ.get("TEMP", "."))
        dest_file = temp_dir / "MeetRecorder-Update.exe"

        try:
            req = urllib.request.Request(self.download_url, headers={"User-Agent": "MeetRecorder-Updater"})
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = response.length or 0
                downloaded = 0
                chunk_size = 64 * 1024

                with open(dest_file, "wb") as out_file:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = int((downloaded / total_size) * 100)
                            self.progress.emit(pct)

            self.finished.emit(str(dest_file))
        except Exception as e:
            self.failed.emit(str(e))

class UpdateDialog(QDialog):
    """Красивое диалоговое окно предложения обновиться с показом списка изменений"""
    def __init__(self, latest_version: str, changelog: str, download_url: str, parent=None):
        super().__init__(parent)
        self.download_url = download_url
        self.setWindowTitle("Доступно обновление Meet Recorder")
        self.setFixedSize(520, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #181A20;
                color: #FFFFFF;
            }
            QLabel {
                color: #E0E0E0;
            }
            QTextEdit {
                background-color: #1E222D;
                border: 1px solid #2B2F3A;
                border-radius: 6px;
                color: #D6D9E0;
                padding: 8px;
            }
            QPushButton {
                background-color: #2A9D8F;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #26867A;
            }
            QPushButton#btn_skip {
                background-color: #3A3F52;
            }
            QPushButton#btn_skip:hover {
                background-color: #4A5068;
            }
            QProgressBar {
                background-color: #1E222D;
                border: 1px solid #3A3F52;
                border-radius: 6px;
                text-align: center;
                color: white;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #00FFCC;
                border-radius: 5px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        lbl_title = QLabel(f"🎉 Вышла новая версия: {latest_version}")
        font_title = QFont("Segoe UI", 13)
        font_title.setBold(True)
        lbl_title.setFont(font_title)
        lbl_title.setStyleSheet("color: #00FFCC;")
        layout.addWidget(lbl_title)

        lbl_current = QLabel(f"Текущая установленная версия: v{APP_VERSION}")
        lbl_current.setStyleSheet("color: #9AA0A6;")
        layout.addWidget(lbl_current)

        lbl_changes = QLabel("Что нового в этом выпуске:")
        lbl_changes.setFont(QFont("Segoe UI", 10))
        layout.addWidget(lbl_changes)

        txt_body = QTextEdit()
        txt_body.setReadOnly(True)
        txt_body.setPlainText(changelog)
        layout.addWidget(txt_body)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        btn_box = QHBoxLayout()
        btn_skip = QPushButton("Напомнить позже")
        btn_skip.setObjectName("btn_skip")
        btn_skip.clicked.connect(self.reject)

        self.btn_update = QPushButton("🚀 Обновить сейчас")
        self.btn_update.clicked.connect(self._start_download)

        btn_box.addWidget(btn_skip)
        btn_box.addStretch()
        btn_box.addWidget(self.btn_update)
        layout.addLayout(btn_box)

    def _start_download(self):
        if not self.download_url:
            self.reject()
            return

        self.btn_update.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.downloader = UpdateDownloadThread(self.download_url, self)
        self.downloader.progress.connect(self.progress_bar.setValue)
        self.downloader.finished.connect(self._on_download_finished)
        self.downloader.failed.connect(self._on_download_failed)
        self.downloader.start()

    def _on_download_finished(self, setup_exe_path: str):
        logger.info(f"[Updater] Обновление скачано: {setup_exe_path}. Запуск установщика...")
        try:
            # Запускаем установщик и закрываем текущее приложение
            subprocess.Popen([setup_exe_path])
            sys.exit(0)
        except Exception as e:
            logger.error(f"[Updater] Не удалось запустить установщик: {e}")
            self.reject()

    def _on_download_failed(self, error: str):
        logger.error(f"[Updater] Ошибка скачивания обновления: {error}")
        self.progress_bar.setVisible(False)
        self.btn_update.setEnabled(True)
