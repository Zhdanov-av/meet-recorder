from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter
from PySide6.QtCore import Signal, QObject

def create_tray_icon(is_recording: bool = False) -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if is_recording:
        painter.setBrush(QColor(230, 57, 70))
        painter.setPen(QColor(255, 255, 255))
    else:
        painter.setBrush(QColor(42, 157, 143))
        painter.setPen(QColor(255, 255, 255))

    painter.drawEllipse(2, 2, 28, 28)
    painter.end()
    return QIcon(pixmap)

class TrayIconManager(QObject):
    start_recording_clicked = Signal()
    open_main_clicked = Signal()
    quit_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tray = QSystemTrayIcon(create_tray_icon(False), parent)
        self.tray.setToolTip("Meet Recorder - Фоновая запись встреч")

        menu = QMenu()
        
        act_start = menu.addAction("🎙️ Быстрая запись (Ctrl+Alt+Z)")
        act_start.triggered.connect(self.start_recording_clicked.emit)

        menu.addSeparator()

        act_main = menu.addAction("🏢 Главное окно (Проекты и Настройки)")
        act_main.triggered.connect(self.open_main_clicked.emit)

        menu.addSeparator()

        act_quit = menu.addAction("❌ Выйти из программы")
        act_quit.triggered.connect(self.quit_clicked.emit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

    def set_recording_state(self, is_recording: bool):
        self.tray.setIcon(create_tray_icon(is_recording))
        if is_recording:
            self.tray.setToolTip("Meet Recorder - 🔴 ИДЁТ ЗАПИСЬ")
        else:
            self.tray.setToolTip("Meet Recorder - Ожидание (Ctrl+Alt+Z)")

    def show_notification(self, title: str, message: str):
        self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 4000)

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_main_clicked.emit()
