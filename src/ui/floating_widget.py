import time
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QTimer, Signal, QPoint
from PySide6.QtGui import QFont

class FloatingRecordingWidget(QWidget):
    stop_requested = Signal()

    def __init__(self, project_name: str = ""):
        super().__init__()
        self.project_name = project_name
        self.start_time = 0
        self.drag_position = QPoint()

        self.init_ui()

    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.container = QWidget(self)
        self.container.setObjectName("recording_container")
        self.container.setStyleSheet("""
            QWidget#recording_container {
                background-color: rgba(18, 22, 30, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 20px;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)

        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(14, 8, 14, 8)
        container_layout.setSpacing(12)

        # 🔴 Индикатор записи
        self.lbl_dot = QLabel("🔴")
        font_dot = QFont("Segoe UI", 11)
        font_dot.setBold(True)
        self.lbl_dot.setFont(font_dot)

        # ⏱️ Живой таймер
        self.lbl_timer = QLabel("00:00:00")
        font_timer = QFont("Consolas", 13)
        font_timer.setBold(True)
        self.lbl_timer.setFont(font_timer)
        self.lbl_timer.setStyleSheet("color: #00FFCC; border: none;")

        # Имя проекта
        self.lbl_project = QLabel(f"[{self.project_name}]")
        font_proj = QFont("Segoe UI", 10)
        self.lbl_project.setFont(font_proj)
        self.lbl_project.setStyleSheet("color: #9AA0A6; border: none;")

        # ⏹️ Кнопка быстрой остановки
        self.btn_stop = QPushButton("⏹ Стоп")
        font_btn = QFont("Segoe UI", 9)
        font_btn.setBold(True)
        self.btn_stop.setFont(font_btn)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E63946, stop:1 #D62828);
                color: white;
                border: none;
                border-radius: 12px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF4D5A, stop:1 #E63946);
            }
        """)
        self.btn_stop.clicked.connect(self.stop_requested.emit)

        container_layout.addWidget(self.lbl_dot)
        container_layout.addWidget(self.lbl_timer)
        container_layout.addWidget(self.lbl_project)
        container_layout.addWidget(self.btn_stop)

        layout.addWidget(self.container)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_timer)

    def start_recording_timer(self):
        self.start_time = time.time()
        self.timer.start(1000)
        
        self.adjustSize()
        screen = self.screen().geometry()
        self.move((screen.width() - self.width()) // 2, 35)
        
        self.show()
        self.raise_()
        self.activateWindow()

    def stop_recording_timer(self):
        self.timer.stop()
        self.hide()

    def _update_timer(self):
        elapsed = int(time.time() - self.start_time)
        mins, secs = divmod(elapsed, 60)
        hours, mins = divmod(mins, 60)
        self.lbl_timer.setText(f"{hours:02d}:{mins:02d}:{secs:02d}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
