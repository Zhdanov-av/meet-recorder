import sys
import os
import threading
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal, QThread, Qt, QTimer
from PySide6.QtGui import QIcon

from src.logger import logger, setup_exception_logging
setup_exception_logging()

from src.config import config, APP_VERSION, get_install_root
from src.retention import cleanup_old_media
from src.audio_recorder import DualChannelAudioRecorder
from src.queue_manager import queue_manager

from src.ui.main_window import MainWindow
from src.ui.tray import TrayIconManager
from src.ui.start_dialog import QuickStartDialog
from src.ui.floating_widget import FloatingRecordingWidget
from src.ui.onboarding_wizard import OnboardingWizardDialog
from src.hotkeys import GlobalHotkeyListener

class MeetRecorderApp(QObject):
    def __init__(self):
        super().__init__()
        logger.info(f"Запуск приложения Meet Recorder v{APP_VERSION}...")
        self.audio_recorder = DualChannelAudioRecorder()

        self.current_audio_path = None
        self.current_project = ""
        self.current_title = ""
        self.is_recording = False

        self.main_window = MainWindow()
        self.tray = TrayIconManager()
        self.floating_widget = None
        self.start_dialog = None
        self.wizard_dialog = None

        # Запуск службы автоочистки кэша
        threading.Thread(target=cleanup_old_media, daemon=True).start()

        # Слушатель глобальных хоткеев
        self.hotkey_listener = GlobalHotkeyListener()
        self.hotkey_listener.hotkey_triggered.connect(self._on_hotkey_pressed, Qt.ConnectionType.QueuedConnection)
        self.hotkey_listener.start()

        # Сигналы трея
        self.tray.open_main_clicked.connect(self.show_main_window)
        self.tray.start_recording_clicked.connect(self._on_hotkey_pressed)
        self.tray.quit_clicked.connect(self.quit_app)

        # Сигналы главного окна
        self.main_window.hotkey_changed.connect(self.hotkey_listener.update_hotkey)
        self.main_window.relaunch_wizard_requested.connect(self._launch_wizard)

        # Сигналы очереди транскрибаций
        queue_manager.queue_changed.connect(self._on_queue_changed)

        # Логика запуска окна или мастера настройки
        if config.get("first_run", True):
            QTimer.singleShot(150, self._launch_wizard)
        else:
            is_autostart = "--autostart" in sys.argv
            if is_autostart and config.get("start_minimized", False):
                hk_name = config.get("hotkey", "Ctrl+Alt+Z")
                self.tray.show_notification("Meet Recorder", f"🎙️ Приложение работает в трее ({hk_name})")
            else:
                QTimer.singleShot(100, self.show_main_window)

    def _launch_wizard(self):
        logger.info("[App] Открытие мастера первичной настройки...")
        self.wizard_dialog = OnboardingWizardDialog()
        if self.wizard_dialog.exec():
            self.main_window.reload_projects_table()
            self.show_main_window()

    def show_main_window(self):
        logger.info("[App] Отображение Главного окна")
        self.main_window.setWindowState(Qt.WindowState.WindowNoState)
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def _on_hotkey_pressed(self):
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_dialog = QuickStartDialog()
            self.start_dialog.recording_started.connect(self.start_recording)
            self.start_dialog.show()
            self.start_dialog.raise_()
            self.start_dialog.activateWindow()

    def start_recording(self, project_name: str, title: str):
        logger.info(f"Старт записи для проекта '{project_name}'")
        self.is_recording = True
        self.current_project = project_name
        self.current_title = title

        self.current_audio_path = self.audio_recorder.start(project_name=project_name)

        if config.get("show_floating_widget", True):
            self.floating_widget = FloatingRecordingWidget(project_name=project_name)
            self.floating_widget.stop_requested.connect(self.stop_recording)
            self.floating_widget.start_recording_timer()

        self.tray.set_recording_state(True)
        self.tray.show_notification("Meet Recorder", f"🔴 Запись запущена: '{project_name}'")

    def stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        logger.info("Остановка записи встречи")

        if self.floating_widget:
            self.floating_widget.stop_recording_timer()
            self.floating_widget = None

        audio_file = self.audio_recorder.stop()

        self.tray.set_recording_state(False)

        task = queue_manager.add_task(
            audio_path=audio_file,
            project_name=self.current_project,
            meeting_title=self.current_title
        )

        self.tray.show_notification(
            "Meet Recorder",
            f"💾 Запись сохранена!\nВстреча '{task['meeting_title']}' добавлена в очередь транскрибации."
        )

    def _on_queue_changed(self, queued_count: int, is_processing: bool):
        if is_processing and queued_count > 0:
            self.tray.show_notification(
                "Meet Recorder",
                f"🔄 Выполняется транскрибация. В очереди ещё: {queued_count}"
            )
        elif not is_processing and queued_count == 0:
            self.tray.show_notification(
                "Meet Recorder",
                "✅ Все встречи в очереди успешно расшифрованы!"
            )

    def quit_app(self):
        logger.info("Завершение работы приложения...")
        self.hotkey_listener.stop()
        self.main_window.is_force_quitting = True
        self.main_window.close()
        QApplication.quit()

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    icon_path = get_install_root() / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    recorder_app = MeetRecorderApp()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
