import sys
import os
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QComboBox, QSpinBox, QLineEdit, QFileDialog, QMessageBox,
    QDialog, QFormLayout, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QFont, QCloseEvent, QDesktopServices, QKeySequence, QIcon

from src.config import config, APP_VERSION, get_base_recordings_dir, get_install_root
from src.queue_manager import queue_manager
from src.audio_recorder import get_audio_devices
from src.updater import UpdateCheckerThread, UpdateDialog
from src.logger import get_logs_dir, logger
from src.hotkeys import format_hotkey_display

def get_whisper_cache_size_mb() -> float:
    try:
        hub_dir = Path.home() / ".cache" / "huggingface" / "hub"
        if not hub_dir.exists():
            return 0.0
        total_bytes = 0
        for p in hub_dir.glob("models--Systran--faster-whisper-*"):
            total_bytes += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        return total_bytes / (1024 * 1024)
    except Exception:
        return 0.0

def clear_whisper_cache() -> int:
    import shutil
    deleted = 0
    try:
        hub_dir = Path.home() / ".cache" / "huggingface" / "hub"
        if hub_dir.exists():
            for p in hub_dir.glob("models--Systran--faster-whisper-*"):
                shutil.rmtree(p, ignore_errors=True)
                deleted += 1
    except Exception as e:
        logger.error(f"Ошибка очистки кэша Whisper: {e}")
    return deleted

class HotkeyCaptureButton(QPushButton):
    """
    Интерактивная кнопка записи горячей клавиши.
    Пользователь кликает -> нажимает любую комбинацию (например Ctrl+Alt+Z или F9) ->
    комбинация автоматически перехватывается без ввода текста вручную.
    """
    hotkey_captured = Signal(str)

    def __init__(self, current_hotkey="<ctrl>+<alt>+z", parent=None):
        super().__init__(parent)
        self.current_hotkey = current_hotkey
        self.is_recording = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.start_recording)
        self.update_style()

    def update_style(self):
        if self.is_recording:
            self.setText("🔴 Нажмите сочетание клавиш (Esc для отмены)...")
            self.setStyleSheet("""
                QPushButton {
                    background-color: #2D3748;
                    color: #00FFCC;
                    border: 2px solid #00FFCC;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-weight: bold;
                    font-size: 13px;
                    text-align: left;
                }
            """)
        else:
            disp = format_hotkey_display(self.current_hotkey)
            self.setText(f"⌨  {disp}   (Нажмите, чтобы изменить)")
            self.setStyleSheet("""
                QPushButton {
                    background-color: #262A36;
                    color: #FFFFFF;
                    border: 1px solid #3A3F52;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-weight: bold;
                    font-size: 13px;
                    text-align: left;
                }
                QPushButton:hover {
                    border-color: #00FFCC;
                    background-color: #2E3444;
                }
            """)

    def start_recording(self):
        self.is_recording = True
        self.update_style()
        self.setFocus()

    def stop_recording(self):
        self.is_recording = False
        self.update_style()
        self.clearFocus()

    def keyPressEvent(self, event):
        if not self.is_recording:
            super().keyPressEvent(event)
            return

        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.stop_recording()
            return

        mods = event.modifiers()
        parts = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("win")

        # Если нажата чисто клавиша-модификатор (Ctrl/Alt/Shift), ждем саму клавишу
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta):
            display_mods = " + ".join([p.capitalize() for p in parts])
            self.setText(f"🔴 {display_mods} + ...")
            return

        # Основная клавиша
        key_name = ""
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            key_name = f"f{key - Qt.Key.Key_F1 + 1}"
        elif key == Qt.Key.Key_Space:
            key_name = "space"
        elif key == Qt.Key.Key_Tab:
            key_name = "tab"
        else:
            text = event.text().strip().lower()
            if text and len(text) == 1 and (text.isalnum() or text in "-=[]\\;',./"):
                key_name = text
            else:
                key_name = QKeySequence(key).toString().lower()

        if key_name and key_name not in parts:
            parts.append(key_name)
            new_hk = "+".join([f"<{p}>" if len(p) > 1 else p for p in parts])
            self.current_hotkey = new_hk
            self.hotkey_captured.emit(new_hk)
            self.stop_recording()

class ProjectEditDialog(QDialog):
    def __init__(self, parent=None, project_name="", project_folder=""):
        super().__init__(parent)
        self.setWindowTitle("Проект")
        self.setFixedWidth(500)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)

        self.setStyleSheet("""
            QDialog {
                background-color: #1E222D;
                color: #FFFFFF;
            }
            QLabel {
                color: #E0E0E0;
                font-size: 13px;
            }
            QLineEdit {
                background-color: #262A36;
                border: 1px solid #3A3F52;
                border-radius: 6px;
                padding: 6px;
                color: white;
            }
            QPushButton {
                background-color: #2A9D8F;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #26867A;
            }
            QPushButton#btn_cancel {
                background-color: #3A3F52;
            }
            QPushButton#btn_cancel:hover {
                background-color: #4A5068;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        form = QFormLayout()

        self.txt_name = QLineEdit(project_name)
        self.txt_folder = QLineEdit(project_folder)
        self.btn_browse = QPushButton("📁 Обзор...")
        self.btn_browse.clicked.connect(self._browse_folder)

        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.txt_folder)
        folder_layout.addWidget(self.btn_browse)

        form.addRow("Название проекта:", self.txt_name)
        form.addRow("Папка для .md отчетов:", folder_layout)

        layout.addLayout(form)

        btn_box = QHBoxLayout()
        btn_ok = QPushButton("Сохранить")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.clicked.connect(self.reject)

        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_ok)
        layout.addLayout(btn_box)

    def _browse_folder(self):
        start_dir = self.txt_folder.text().strip() or str(Path.home() / "Documents")
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку проекта для сохранения .md файлов",
            start_dir,
            QFileDialog.Option.DontUseNativeDialog
        )
        if folder:
            self.txt_folder.setText(folder)

    def get_data(self):
        return self.txt_name.text().strip(), self.txt_folder.text().strip()

class MainWindow(QMainWindow):
    hotkey_changed = Signal(str)
    relaunch_wizard_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Meet Recorder v{APP_VERSION} - Управление и История")
        self.resize(820, 560)
        self.is_force_quitting = False

        icon_path = get_install_root() / "assets" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.init_ui()

        queue_manager.task_added.connect(self._on_task_updated)
        queue_manager.task_updated.connect(self._on_task_updated)

    def init_ui(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #181A20;
                color: #E0E0E0;
                font-family: 'Segoe UI', sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid #2B2F3A;
                background-color: #1E222D;
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #181A20;
                color: #A0A5B5;
                padding: 10px 20px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #1E222D;
                color: #00FFCC;
                border-bottom: 2px solid #00FFCC;
            }
            QPushButton {
                background-color: #2A9D8F;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #26867A;
            }
            QPushButton#btn_danger {
                background-color: #E63946;
            }
            QPushButton#btn_danger:hover {
                background-color: #D62828;
            }
            QPushButton#btn_secondary {
                background-color: #3A3F52;
            }
            QPushButton#btn_secondary:hover {
                background-color: #4A5068;
            }
            QTableWidget {
                background-color: #1E222D;
                gridline-color: #2B2F3A;
                border: none;
            }
            QHeaderView::section {
                background-color: #262A36;
                color: #00FFCC;
                padding: 6px;
                border: none;
                font-weight: bold;
            }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #262A36;
                border: 1px solid #3A3F52;
                border-radius: 6px;
                padding: 6px;
                color: white;
            }
            QFrame#card {
                background-color: #1E222D;
                border: 1px solid #2B2F3A;
                border-radius: 8px;
                padding: 12px;
            }
        """)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 14, 14, 14)

        self.tabs = QTabWidget()
        self.tab_history = QWidget()
        self.tab_projects = QWidget()
        self.tab_settings = QWidget()

        self._setup_history_tab()
        self._setup_projects_tab()
        self._setup_settings_tab()

        self.tabs.addTab(self.tab_history, "📜 История и Очередь")
        self.tabs.addTab(self.tab_projects, "📁 Управление Проектами")
        self.tabs.addTab(self.tab_settings, "⚙️ Настройки")

        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

    def _setup_history_tab(self):
        layout = QVBoxLayout(self.tab_history)
        layout.setContentsMargins(16, 16, 16, 16)

        lbl = QLabel("История всех записанных встреч и их текущий статус расшифровки:")
        lbl.setFont(QFont("Segoe UI", 10))
        layout.addWidget(lbl)

        self.table_history = QTableWidget()
        self.table_history.setColumnCount(5)
        self.table_history.setHorizontalHeaderLabels(["Дата/Время", "Проект", "Встреча", "Статус", "Файл отчета (.md)"])
        self.table_history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table_history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table_history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table_history.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table_history.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table_history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        layout.addWidget(self.table_history)

        btn_layout = QHBoxLayout()
        self.btn_open_file = QPushButton("📄 Открыть отчёт (.md)")
        self.btn_open_file.clicked.connect(self._open_selected_md)

        self.btn_open_folder = QPushButton("📂 Открыть папку отчёта")
        self.btn_open_folder.setObjectName("btn_secondary")
        self.btn_open_folder.clicked.connect(self._open_selected_folder)

        btn_layout.addWidget(self.btn_open_file)
        btn_layout.addWidget(self.btn_open_folder)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)
        self.reload_history_table()

    def reload_history_table(self):
        self.table_history.setRowCount(0)
        tasks = queue_manager.get_all_tasks()
        for task in tasks:
            row = self.table_history.rowCount()
            self.table_history.insertRow(row)

            self.table_history.setItem(row, 0, QTableWidgetItem(task.get("created_at", "")))
            self.table_history.setItem(row, 1, QTableWidgetItem(task.get("project_name", "")))
            self.table_history.setItem(row, 2, QTableWidgetItem(task.get("meeting_title", "")))

            status_item = QTableWidgetItem(task.get("status", ""))
            status = task.get("status", "")
            if "Завершено" in status:
                status_item.setForeground(Qt.GlobalColor.green)
            elif "обработке" in status:
                status_item.setForeground(Qt.GlobalColor.cyan)
            elif "очереди" in status:
                status_item.setForeground(Qt.GlobalColor.yellow)
            elif "Ошибка" in status:
                status_item.setForeground(Qt.GlobalColor.red)

            self.table_history.setItem(row, 3, status_item)

            md_path = task.get("result_md", "")
            md_display = Path(md_path).name if md_path else ""
            item_md = QTableWidgetItem(md_display)
            item_md.setData(Qt.ItemDataRole.UserRole, md_path)
            self.table_history.setItem(row, 4, item_md)

    def _on_task_updated(self, task: dict):
        self.reload_history_table()

    def _open_selected_md(self):
        selected = self.table_history.currentRow()
        if selected >= 0:
            md_path = self.table_history.item(selected, 4).data(Qt.ItemDataRole.UserRole)
            if md_path and os.path.exists(md_path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(md_path))
            else:
                QMessageBox.warning(self, "Файл", "Файл отчёта ещё не создан или не найден.")

    def _open_selected_folder(self):
        selected = self.table_history.currentRow()
        if selected >= 0:
            md_path = self.table_history.item(selected, 4).data(Qt.ItemDataRole.UserRole)
            if md_path and os.path.exists(md_path):
                folder = str(Path(md_path).parent)
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            else:
                proj_name = self.table_history.item(selected, 1).text()
                proj_folder = config.get("projects", {}).get(proj_name, "")
                if proj_folder and os.path.exists(proj_folder):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(proj_folder))
                else:
                    QMessageBox.warning(self, "Папка", "Папка проекта не найдена.")

    def _setup_projects_tab(self):
        layout = QVBoxLayout(self.tab_projects)
        layout.setContentsMargins(16, 16, 16, 16)

        lbl = QLabel("Список ваших проектов и папок для сохранения .md транскриптов:")
        lbl.setFont(QFont("Segoe UI", 10))
        layout.addWidget(lbl)

        self.table_projects = QTableWidget()
        self.table_projects.setColumnCount(2)
        self.table_projects.setHorizontalHeaderLabels(["Имя проекта", "Папка для сохранения (.md)"])
        self.table_projects.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table_projects.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_projects.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_projects.doubleClicked.connect(self._edit_project)

        layout.addWidget(self.table_projects)

        btn_layout = QHBoxLayout()
        self.btn_add_proj = QPushButton("+ Добавить проект")
        self.btn_add_proj.clicked.connect(self._add_project)

        self.btn_edit_proj = QPushButton("✏️ Редактировать")
        self.btn_edit_proj.setObjectName("btn_secondary")
        self.btn_edit_proj.clicked.connect(self._edit_project)

        self.btn_del_proj = QPushButton("🗑 Удалить")
        self.btn_del_proj.setObjectName("btn_danger")
        self.btn_del_proj.clicked.connect(self._remove_project)

        btn_layout.addWidget(self.btn_add_proj)
        btn_layout.addWidget(self.btn_edit_proj)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_del_proj)

        layout.addLayout(btn_layout)
        self.reload_projects_table()

    def reload_projects_table(self):
        self.table_projects.setRowCount(0)
        projects = config.get("projects", {})
        for name, folder in projects.items():
            row = self.table_projects.rowCount()
            self.table_projects.insertRow(row)
            self.table_projects.setItem(row, 0, QTableWidgetItem(name))
            self.table_projects.setItem(row, 1, QTableWidgetItem(folder))

    def _add_project(self):
        dlg = ProjectEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, folder = dlg.get_data()
            if name and folder:
                config.add_project(name, folder)
                self.reload_projects_table()

    def _edit_project(self):
        selected = self.table_projects.currentRow()
        if selected >= 0:
            old_name = self.table_projects.item(selected, 0).text()
            old_folder = self.table_projects.item(selected, 1).text()
            
            dlg = ProjectEditDialog(self, project_name=old_name, project_folder=old_folder)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                new_name, new_folder = dlg.get_data()
                if new_name and new_folder:
                    if new_name != old_name:
                        config.remove_project(old_name)
                    config.add_project(new_name, new_folder)
                    self.reload_projects_table()

    def _remove_project(self):
        selected = self.table_projects.currentRow()
        if selected >= 0:
            proj_name = self.table_projects.item(selected, 0).text()
            reply = QMessageBox.question(
                self, "Удаление", f"Удалить проект '{proj_name}' из списка?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                config.remove_project(proj_name)
                self.reload_projects_table()

    def _setup_settings_tab(self):
        scroll = QScrollArea(self.tab_settings)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        # 1. 🚀 Интеграция с Windows
        card_win = QFrame()
        card_win.setObjectName("card")
        c_win_lay = QVBoxLayout(card_win)
        c_win_lay.setSpacing(8)
        c_win_lay.addWidget(QLabel("<b>🚀 Интеграция с Windows (по умолчанию выключено)</b>"))

        self.chk_autostart = QCheckBox("Запускать приложение при старте Windows")
        self.chk_autostart.setChecked(config.get("autostart", False))
        c_win_lay.addWidget(self.chk_autostart)

        self.chk_minimized = QCheckBox("Запускать свернутым в трей (не открывать окно при старте)")
        self.chk_minimized.setChecked(config.get("start_minimized", False))
        c_win_lay.addWidget(self.chk_minimized)
        layout.addWidget(card_win)

        # 2. ⌨️ Горячие клавиши (Интерактивная запись комбинаций)
        card_hk = QFrame()
        card_hk.setObjectName("card")
        c_hk_lay = QVBoxLayout(card_hk)
        c_hk_lay.setSpacing(8)
        c_hk_lay.addWidget(QLabel("<b>⌨️ Горячая клавиша для старта и остановки записи:</b>"))

        hk_box = QHBoxLayout()
        current_hk = config.get("hotkey", "<ctrl>+<alt>+z")
        self.btn_hotkey = HotkeyCaptureButton(current_hk)

        btn_reset_hk = QPushButton("Сброс (Ctrl+Alt+Z)")
        btn_reset_hk.setObjectName("btn_secondary")
        btn_reset_hk.clicked.connect(self._reset_hotkey_default)

        hk_box.addWidget(self.btn_hotkey, 1)
        hk_box.addWidget(btn_reset_hk)
        c_hk_lay.addLayout(hk_box)

        lbl_hk_hint = QLabel("<i>Нажмите кнопку выше и зажмите нужные клавиши (например Ctrl + Alt + Z или F9).</i>")
        lbl_hk_hint.setStyleSheet("color: #9AA0A6; font-size: 11px;")
        c_hk_lay.addWidget(lbl_hk_hint)

        layout.addWidget(card_hk)

        # 3. 🎙️ Аудиоустройства и Сигналы
        card_audio = QFrame()
        card_audio.setObjectName("card")
        c_aud_lay = QVBoxLayout(card_audio)
        c_aud_lay.setSpacing(8)
        c_aud_lay.addWidget(QLabel("<b>🎙️ Аудиоустройства и Сигналы:</b>"))

        mics, speakers = get_audio_devices()

        c_aud_lay.addWidget(QLabel("Микрофон (голос пользователя):"))
        self.combo_mic = QComboBox()
        self.combo_mic.addItem("По умолчанию в системе", "")
        sel_mic = config.get("selected_mic", "")
        for m in mics:
            self.combo_mic.addItem(m, m)
            if m == sel_mic:
                self.combo_mic.setCurrentIndex(self.combo_mic.count() - 1)
        c_aud_lay.addWidget(self.combo_mic)

        c_aud_lay.addWidget(QLabel("Динамики (голоса собеседников):"))
        self.combo_spk = QComboBox()
        self.combo_spk.addItem("По умолчанию в системе", "")
        sel_spk = config.get("selected_speaker", "")
        for s in speakers:
            self.combo_spk.addItem(s, s)
            if s == sel_spk:
                self.combo_spk.setCurrentIndex(self.combo_spk.count() - 1)
        c_aud_lay.addWidget(self.combo_spk)

        self.chk_beep = QCheckBox("Звуковой сигнал (бип) при старте и завершении записи")
        self.chk_beep.setChecked(config.get("play_sound_signals", True))
        c_aud_lay.addWidget(self.chk_beep)

        self.chk_floating = QCheckBox("Показывать плавающий индикатор с таймером во время записи")
        self.chk_floating.setChecked(config.get("show_floating_widget", True))
        c_aud_lay.addWidget(self.chk_floating)

        layout.addWidget(card_audio)

        # 4. 🧠 ИИ-Модель и Вычисления
        card_ai = QFrame()
        card_ai.setObjectName("card")
        c_ai_lay = QVBoxLayout(card_ai)
        c_ai_lay.setSpacing(8)
        c_ai_lay.addWidget(QLabel("<b>🧠 Локальная модель Whisper:</b>"))

        self.combo_model = QComboBox()
        self.combo_model.addItems(["medium (Рекомендуется)", "small (Быстрая)", "large-v3-turbo (Максимальная точность)"])
        current_m = config.get("whisper_model", "medium")
        for i in range(self.combo_model.count()):
            if current_m in self.combo_model.itemText(i):
                self.combo_model.setCurrentIndex(i)
                break
        c_ai_lay.addWidget(self.combo_model)

        c_ai_lay.addWidget(QLabel("Режим вычислений:"))
        self.combo_device = QComboBox()
        self.combo_device.addItem("CPU (Стабильный режим на любом ПК)", "cpu")
        self.combo_device.addItem("GPU (NVIDIA CUDA Ускорение в 5 раз)", "cuda")
        if config.get("compute_device", "cpu") == "cuda":
            self.combo_device.setCurrentIndex(1)
        c_ai_lay.addWidget(self.combo_device)

        layout.addWidget(card_ai)

        # 5. 📁 Хранилище и Очистка
        card_storage = QFrame()
        card_storage.setObjectName("card")
        c_stor_lay = QVBoxLayout(card_storage)
        c_stor_lay.setSpacing(8)
        c_stor_lay.addWidget(QLabel("<b>📁 Хранение и Автоочистка записей:</b>"))

        ret_h = QHBoxLayout()
        ret_h.addWidget(QLabel("Удалять аудиозаписи из папки recordings через:"))
        self.spin_retention = QSpinBox()
        self.spin_retention.setRange(1, 90)
        self.spin_retention.setValue(config.get("retention_days", 7))
        self.spin_retention.setSuffix(" дней")
        ret_h.addWidget(self.spin_retention)
        ret_h.addStretch()
        c_stor_lay.addLayout(ret_h)

        stor_btn_h = QHBoxLayout()
        btn_open_rec = QPushButton("📂 Открыть папку записей")
        btn_open_rec.setObjectName("btn_secondary")
        btn_open_rec.clicked.connect(self._open_recordings_folder)

        btn_open_logs = QPushButton("📋 Открыть папку с логами")
        btn_open_logs.setObjectName("btn_secondary")
        btn_open_logs.clicked.connect(self._open_logs_folder)

        stor_btn_h.addWidget(btn_open_rec)
        stor_btn_h.addWidget(btn_open_logs)
        stor_btn_h.addStretch()
        c_stor_lay.addLayout(stor_btn_h)

        # Кэш моделей Whisper
        c_stor_lay.addWidget(QLabel("<b>Кэш моделей искусственного интеллекта (Whisper):</b>"))
        cache_h = QHBoxLayout()
        self.lbl_whisper_cache = QLabel("Кэш моделей на диске: расчет...")
        self.lbl_whisper_cache.setStyleSheet("color: #00FFCC;")
        btn_clear_whisper = QPushButton("🗑️ Очистить кэш Whisper")
        btn_clear_whisper.setObjectName("btn_secondary")
        btn_clear_whisper.clicked.connect(self._clear_whisper_cache_clicked)
        cache_h.addWidget(self.lbl_whisper_cache)
        cache_h.addStretch()
        cache_h.addWidget(btn_clear_whisper)
        c_stor_lay.addLayout(cache_h)

        lbl_cache_hint = QLabel("<i>Модели сохраняются в общем кэше пользователя (%USERPROFILE%\\.cache\\huggingface) и повторно не скачиваются при переустановке программы.</i>")
        lbl_cache_hint.setStyleSheet("color: #9AA0A6; font-size: 11px;")
        lbl_cache_hint.setWordWrap(True)
        c_stor_lay.addWidget(lbl_cache_hint)

        # Деинсталляция
        unins_h = QHBoxLayout()
        lbl_unins = QLabel("Деинсталляция программы (unins000.exe):")
        lbl_unins.setStyleSheet("color: #9AA0A6;")
        btn_unins = QPushButton("❌ Удалить приложение")
        btn_unins.setObjectName("btn_cancel")
        btn_unins.clicked.connect(self._launch_uninstaller)
        unins_h.addWidget(lbl_unins)
        unins_h.addStretch()
        unins_h.addWidget(btn_unins)
        c_stor_lay.addLayout(unins_h)

        layout.addWidget(card_storage)

        # 6. 🔄 Обновления и Диагностика
        card_update = QFrame()
        card_update.setObjectName("card")
        c_up_lay = QHBoxLayout(card_update)
        
        lbl_v = QLabel(f"<b>Meet Recorder v{APP_VERSION}</b>")
        lbl_v.setStyleSheet("color: #00FFCC;")
        btn_check_up = QPushButton("🔄 Проверить обновления")
        btn_check_up.clicked.connect(self._check_updates)

        btn_wizard = QPushButton("🧙 Запустить мастер настройки")
        btn_wizard.setObjectName("btn_secondary")
        btn_wizard.clicked.connect(self.relaunch_wizard_requested.emit)

        c_up_lay.addWidget(lbl_v)
        c_up_lay.addStretch()
        c_up_lay.addWidget(btn_wizard)
        c_up_lay.addWidget(btn_check_up)

        layout.addWidget(card_update)

        # Кнопка Сохранить внизу
        btn_save = QPushButton("💾 Сохранить настройки")
        btn_save.clicked.connect(self._save_settings)
        layout.addWidget(btn_save)

        scroll.setWidget(container)

        tab_lay = QVBoxLayout(self.tab_settings)
        tab_lay.setContentsMargins(0, 0, 0, 0)
        tab_lay.addWidget(scroll)

        self._update_whisper_cache_label()

    def _reset_hotkey_default(self):
        self.btn_hotkey.current_hotkey = "<ctrl>+<alt>+z"
        self.btn_hotkey.update_style()

    def _open_recordings_folder(self):
        rec_dir = get_base_recordings_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(rec_dir)))

    def _open_logs_folder(self):
        log_dir = get_logs_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    def _update_whisper_cache_label(self):
        mb = get_whisper_cache_size_mb()
        if mb >= 1024:
            text = f"Кэш моделей на диске: <b>{mb / 1024:.2f} ГБ</b>"
        elif mb > 0:
            text = f"Кэш моделей на диске: <b>{mb:.1f} МБ</b>"
        else:
            text = "Кэш моделей на диске: <b>пусто (0 МБ)</b>"
        self.lbl_whisper_cache.setText(text)

    def _clear_whisper_cache_clicked(self):
        mb = get_whisper_cache_size_mb()
        if mb == 0:
            QMessageBox.information(self, "Кэш пуст", "Кэш моделей Whisper уже пуст.")
            return

        size_str = f"{mb / 1024:.2f} ГБ" if mb >= 1024 else f"{mb:.1f} МБ"
        reply = QMessageBox.question(
            self,
            "Очистка кэша моделей Whisper",
            f"Текущий размер кэша моделей: {size_str}.\n\n"
            "Удалить скачанные модели из папки пользователя (.cache/huggingface)?\n"
            "При следующей записи встреч программе потребуется загрузить выбранную модель заново.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            del_count = clear_whisper_cache()
            self._update_whisper_cache_label()
            QMessageBox.information(
                self,
                "Кэш очищен",
                f"Кэш моделей Whisper успешно удален ({size_str} освобождено)!"
            )

    def _launch_uninstaller(self):
        uninstaller = get_install_root() / "unins000.exe"
        if uninstaller.exists():
            reply = QMessageBox.question(
                self,
                "Деинсталляция Meet Recorder",
                "Вы действительно хотите запустить деинсталлятор и удалить программу?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                subprocess.Popen([str(uninstaller)])
                self.is_force_quitting = True
                self.close()
                QApplication.quit()
        else:
            QMessageBox.information(
                self,
                "Деинсталлятор",
                f"Файл деинсталлятора (unins000.exe) создается автоматически при установке программы инсталлятором (Setup.exe) в директории:\n{get_install_root()}\n\n"
                "Также удалить программу можно в любое время через 'Параметры Windows' -> 'Приложения' -> 'Установленные приложения'."
            )

    def _check_updates(self):
        self.checker = UpdateCheckerThread(parent=self)
        self.checker.check_finished.connect(self._on_update_check_result)
        self.checker.check_failed.connect(lambda err: QMessageBox.warning(self, "Обновления", f"Не удалось проверить обновления: {err}"))
        self.checker.start()

    def _on_update_check_result(self, has_update: bool, latest_v: str, changelog: str, download_url: str):
        if has_update:
            dlg = UpdateDialog(latest_v, changelog, download_url, self)
            dlg.exec()
        else:
            QMessageBox.information(self, "Обновления", f"У вас установлена самая актуальная версия v{APP_VERSION}!")

    def _save_settings(self):
        autostart = self.chk_autostart.isChecked()
        config.set("autostart", autostart)
        config.update_autostart_registry(autostart)

        config.set("start_minimized", self.chk_minimized.isChecked())

        old_hk = config.get("hotkey", "<ctrl>+<alt>+z")
        new_hk = self.btn_hotkey.current_hotkey
        config.set("hotkey", new_hk)
        if new_hk != old_hk:
            self.hotkey_changed.emit(new_hk)

        config.set("selected_mic", self.combo_mic.currentData() or "")
        config.set("selected_speaker", self.combo_spk.currentData() or "")
        config.set("play_sound_signals", self.chk_beep.isChecked())
        config.set("show_floating_widget", self.chk_floating.isChecked())

        model_text = self.combo_model.currentText().split()[0]
        config.set("whisper_model", model_text)

        config.set("compute_device", self.combo_device.currentData() or "cpu")
        config.set("retention_days", self.spin_retention.value())

        QMessageBox.information(self, "Настройки", "Настройки успешно сохранены!")

    def closeEvent(self, event: QCloseEvent):
        if not self.is_force_quitting:
            event.ignore()
            self.hide()
        else:
            event.accept()
