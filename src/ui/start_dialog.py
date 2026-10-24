from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QPushButton
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from src.config import config

class QuickStartDialog(QDialog):
    recording_started = Signal(str, str)  # project_name, meeting_title

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Запуск записи встречи")
        self.setFixedWidth(400)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1E222D;
                color: #FFFFFF;
                border-radius: 10px;
            }
            QLabel {
                color: #E0E0E0;
                font-size: 13px;
                border: none;
            }
            QComboBox, QLineEdit {
                background-color: #2A2E3D;
                color: #FFFFFF;
                border: 1px solid #3A3F52;
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 13px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QPushButton#btn_start {
                background-color: #2A9D8F;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton#btn_start:hover {
                background-color: #26867A;
            }
            QPushButton#btn_cancel {
                background-color: #3A3F52;
                color: white;
                font-size: 13px;
                border: none;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton#btn_cancel:hover {
                background-color: #4A5068;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # Заголовок
        title = QLabel("🎙️ Запись встречи")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #00FFCC; border: none;")
        layout.addWidget(title)

        # Выбор проекта
        lbl_project = QLabel("Выберите проект:")
        self.combo_project = QComboBox()
        self.refresh_projects()
        layout.addWidget(lbl_project)
        layout.addWidget(self.combo_project)

        # Название встречи (опционально)
        lbl_title = QLabel("Название встречи (опционально):")
        self.txt_title = QLineEdit()
        self.txt_title.setPlaceholderText("Например: Обсуждение задач")
        layout.addWidget(lbl_title)
        layout.addWidget(self.txt_title)

        # Кнопки
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_start = QPushButton("▶ Начать запись")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self._on_start)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_start)
        layout.addLayout(btn_layout)

    def refresh_projects(self):
        self.combo_project.clear()
        projects = config.get("projects", {})
        if not projects:
            self.combo_project.addItem("Общий проект (По умолчанию)")
        else:
            for proj_name in projects.keys():
                self.combo_project.addItem(proj_name)
        
        last_proj = config.get("last_project", "")
        idx = self.combo_project.findText(last_proj)
        if idx >= 0:
            self.combo_project.setCurrentIndex(idx)

    def _on_start(self):
        project = self.combo_project.currentText()
        config.set("last_project", project)
        title = self.txt_title.text().strip()

        self.recording_started.emit(project, title)
        self.accept()
