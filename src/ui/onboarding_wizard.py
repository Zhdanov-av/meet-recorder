import os
import sys
import time
import threading
import numpy as np
import soundcard as sc
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QStackedWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QProgressBar,
    QFileDialog, QMessageBox, QFrame
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QFont, QColor

from src.config import config
from src.audio_recorder import get_audio_devices, get_active_devices
from src.logger import logger

class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()

class ModelDownloadWorker(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, model_size: str, device: str = "cpu"):
        super().__init__()
        self.model_size = model_size
        self.device = device

    def run(self):
        try:
            logger.info(f"[Onboarding] Предварительная загрузка модели '{self.model_size}'...")
            from faster_whisper import WhisperModel
            # Всегда загружаем на CPU для гарантированного скачивания весов без зависимости от драйверов CUDA
            WhisperModel(self.model_size, device="cpu", compute_type="int8")
            logger.info(f"[Onboarding] Модель '{self.model_size}' успешно загружена в кэш!")
            self.finished_signal.emit(True, "")
        except Exception as e:
            logger.error(f"[Onboarding] Сбой загрузки модели: {e}")
            self.finished_signal.emit(False, str(e))

class AudioLevelMonitor(QThread):
    levels_updated = Signal(int, int)  # mic_level (0-100), speaker_level (0-100)

    def __init__(self, mic_name="", spk_name="", parent=None):
        super().__init__(parent)
        self.is_monitoring = True
        self.mic_name = mic_name
        self.spk_name = spk_name

    def stop(self):
        self.is_monitoring = False

    def run(self):
        sample_rate = 22050
        block_size = int(sample_rate * 0.08)

        mic = None
        loopback = None

        try:
            for m in sc.all_microphones(include_loopback=False):
                if m.name == self.mic_name:
                    mic = m
                    break
            if mic is None:
                mic = sc.default_microphone()
        except Exception:
            pass

        try:
            spk = None
            for s in sc.all_speakers():
                if s.name == self.spk_name:
                    spk = s
                    break
            if spk is None:
                spk = sc.default_speaker()
            loopback = sc.get_microphone(id=spk.id, include_loopback=True)
        except Exception:
            pass

        while self.is_monitoring:
            mic_val = 0
            spk_val = 0

            if mic:
                try:
                    with mic.recorder(samplerate=sample_rate, channels=1) as r:
                        chunk = r.record(block_size)
                        rms = np.sqrt(np.mean(chunk**2))
                        # Масштабируем RMS в шкалу 0-100
                        mic_val = int(min(100, rms * 400))
                except Exception:
                    pass

            if loopback:
                try:
                    with loopback.recorder(samplerate=sample_rate, channels=1) as r:
                        chunk = r.record(block_size)
                        rms = np.sqrt(np.mean(chunk**2))
                        spk_val = int(min(100, rms * 350))
                except Exception:
                    pass

            self.levels_updated.emit(mic_val, spk_val)
            time.sleep(0.04)

class OnboardingWizardDialog(QDialog):
    """
    Пошаговый мастер первого запуска:
    Шаг 1: Проверка 2-х каналов звука (живые VU-метры)
    Шаг 2: Создание первого проекта и выбор папки для его .md файлов
    Шаг 3: Выбор и предзагрузка модели Whisper с прогресс-баром
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Meet Recorder - Мастер первого запуска")
        self.setFixedSize(620, 520)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)

        self.monitor = None
        self.download_worker = None

        self.init_ui()
        self._start_audio_monitor()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #181A20;
                color: #FFFFFF;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #E0E0E0;
            }
            QLineEdit, QComboBox {
                background-color: #262A36;
                border: 1px solid #3A3F52;
                border-radius: 6px;
                padding: 7px;
                color: white;
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
            QPushButton#btn_secondary {
                background-color: #3A3F52;
            }
            QPushButton#btn_secondary:hover {
                background-color: #4A5068;
            }
            QProgressBar {
                background-color: #262A36;
                border: 1px solid #3A3F52;
                border-radius: 6px;
                height: 14px;
                text-align: center;
                color: transparent;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2A9D8F, stop:1 #00FFCC);
                border-radius: 5px;
            }
            QFrame#card {
                background-color: #1E222D;
                border: 1px solid #2B2F3A;
                border-radius: 10px;
                padding: 14px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Создаем страницы мастера
        self.page1 = self._create_page_sound()
        self.page2 = self._create_page_project()
        self.page3 = self._create_page_model()

        self.stack.addWidget(self.page1)
        self.stack.addWidget(self.page2)
        self.stack.addWidget(self.page3)

        # Нижняя панель навигации
        self.nav_layout = QHBoxLayout()
        self.lbl_step = QLabel("Шаг 1 из 3")
        self.lbl_step.setStyleSheet("color: #9AA0A6; font-size: 11px;")

        self.btn_prev = QPushButton("← Назад")
        self.btn_prev.setObjectName("btn_secondary")
        self.btn_prev.setVisible(False)
        self.btn_prev.clicked.connect(self._go_prev)

        self.btn_next = QPushButton("Далее →")
        self.btn_next.clicked.connect(self._go_next)

        self.nav_layout.addWidget(self.lbl_step)
        self.nav_layout.addStretch()
        self.nav_layout.addWidget(self.btn_prev)
        self.nav_layout.addWidget(self.btn_next)

        layout.addLayout(self.nav_layout)

    def _create_page_sound(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("🎙️ Шаг 1: Проверка 2-х каналов звука")
        f = QFont("Segoe UI", 13)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet("color: #00FFCC;")
        lay.addWidget(title)

        desc = QLabel("Meet Recorder одновременно записывает ваш голос и системный звук собеседников. Проверьте уровни:")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #B0B5C5;")
        lay.addWidget(desc)

        card = QFrame()
        card.setObjectName("card")
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(14)

        # Канал 1: Микрофон
        c_lay.addWidget(QLabel("🎤 <b>Канал 1: Ваш микрофон (голос)</b>"))
        mics, speakers = get_audio_devices()

        self.combo_mic = NoWheelComboBox()
        self.combo_mic.addItem("По умолчанию в системе", "")
        for m in mics:
            self.combo_mic.addItem(m, m)
        self.combo_mic.currentIndexChanged.connect(self._on_devices_changed)
        c_lay.addWidget(self.combo_mic)

        self.bar_mic = QProgressBar()
        self.bar_mic.setRange(0, 100)
        c_lay.addWidget(self.bar_mic)

        lbl_mic_hint = QLabel("<i>Скажите что-нибудь вслух — полоска должна двигаться.</i>")
        lbl_mic_hint.setStyleSheet("color: #9AA0A6; font-size: 11px;")
        c_lay.addWidget(lbl_mic_hint)

        c_lay.addSpacing(6)

        # Канал 2: Динамики
        c_lay.addWidget(QLabel("🔊 <b>Канал 2: Системные динамики (голоса собеседников)</b>"))
        self.combo_spk = NoWheelComboBox()
        self.combo_spk.addItem("По умолчанию в системе", "")
        for s in speakers:
            self.combo_spk.addItem(s, s)
        self.combo_spk.currentIndexChanged.connect(self._on_devices_changed)
        c_lay.addWidget(self.combo_spk)

        self.bar_spk = QProgressBar()
        self.bar_spk.setRange(0, 100)
        c_lay.addWidget(self.bar_spk)

        spk_h = QHBoxLayout()
        lbl_spk_hint = QLabel("<i>Нажмите кнопку для проверки захвата звука:</i>")
        lbl_spk_hint.setStyleSheet("color: #9AA0A6; font-size: 11px;")
        btn_test_sound = QPushButton("🎵 Проверить системный звук")
        btn_test_sound.setObjectName("btn_secondary")
        btn_test_sound.clicked.connect(self._play_test_sound)

        spk_h.addWidget(lbl_spk_hint)
        spk_h.addStretch()
        spk_h.addWidget(btn_test_sound)
        c_lay.addLayout(spk_h)

        lay.addWidget(card)
        lay.addStretch()
        return w

    def _create_page_project(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("📁 Шаг 2: Первый рабочий проект")
        f = QFont("Segoe UI", 13)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet("color: #00FFCC;")
        lay.addWidget(title)

        desc = QLabel("Создайте ваш первый проект и укажите папку, куда будут сохраняться текстовые отчеты .md и аудиозаписи встреч:")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #B0B5C5;")
        lay.addWidget(desc)

        card = QFrame()
        card.setObjectName("card")
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(14)

        c_lay.addWidget(QLabel("<b>Название проекта:</b>"))
        self.txt_proj_name = QLineEdit("Общее")
        c_lay.addWidget(self.txt_proj_name)

        c_lay.addWidget(QLabel("<b>Папка проекта (для отчетов и записей):</b>"))
        default_folder = str(Path.home() / "Documents" / "Встречи")
        self.txt_proj_folder = QLineEdit(default_folder)
        btn_browse = QPushButton("📁 Обзор...")
        btn_browse.setObjectName("btn_secondary")
        btn_browse.clicked.connect(self._browse_project_folder)

        f_lay = QHBoxLayout()
        f_lay.addWidget(self.txt_proj_folder)
        f_lay.addWidget(btn_browse)
        c_lay.addLayout(f_lay)

        note = QLabel("ℹ️ <i>В этой папке будут сохраняться протоколы .md, а аудиофайлы — в подпапку <b>recordings/</b> с автоудалением через 7 дней.</i>")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9AA0A6; font-size: 11px;")
        c_lay.addWidget(note)

        lay.addWidget(card)
        lay.addStretch()
        return w

    def _create_page_model(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("🧠 Шаг 3: Локальная модель Whisper")
        f = QFont("Segoe UI", 13)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet("color: #00FFCC;")
        lay.addWidget(title)

        desc = QLabel("Для автономной работы без интернета требуется локальная модель распознавания речи:")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #B0B5C5;")
        lay.addWidget(desc)

        card = QFrame()
        card.setObjectName("card")
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(14)

        c_lay.addWidget(QLabel("<b>Выберите модель:</b>"))
        self.combo_model = NoWheelComboBox()
        self.combo_model.addItems([
            "medium (Рекомендуется, ~1.5 ГБ, высокий баланс)",
            "small (~500 МБ, быстрая для слабых ПК)",
            "large-v3-turbo (~1.5 ГБ, максимальная точность)"
        ])
        self.combo_model.currentIndexChanged.connect(self._check_selected_model_cached)
        c_lay.addWidget(self.combo_model)

        self.btn_download_model = QPushButton("📥 Загрузить модель в локальный кэш")
        self.btn_download_model.clicked.connect(self._start_model_download)
        c_lay.addWidget(self.btn_download_model)

        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 0)  # Бегущая полоса активности
        self.download_progress.setVisible(False)
        c_lay.addWidget(self.download_progress)

        self.lbl_model_status = QLabel("Проверка наличия модели...")
        self.lbl_model_status.setStyleSheet("color: #9AA0A6;")
        c_lay.addWidget(self.lbl_model_status)

        self._check_selected_model_cached()

        lay.addWidget(card)
        lay.addStretch()
        return w

    def _play_test_sound(self):
        def _beep():
            try:
                import winsound
                winsound.Beep(1200, 200)
                winsound.Beep(1500, 250)
            except Exception:
                pass
        threading.Thread(target=_beep, daemon=True).start()

    def _start_audio_monitor(self):
        if self.monitor:
            self.monitor.stop()
            self.monitor.wait()

        mic = self.combo_mic.currentData() or ""
        spk = self.combo_spk.currentData() or ""
        self.monitor = AudioLevelMonitor(mic, spk, self)
        self.monitor.levels_updated.connect(self._on_levels_updated)
        self.monitor.start()

    def _on_levels_updated(self, mic_val: int, spk_val: int):
        self.bar_mic.setValue(mic_val)
        self.bar_spk.setValue(spk_val)

    def _on_devices_changed(self):
        self._start_audio_monitor()

    def _browse_project_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку проекта (для отчетов и записей)",
            self.txt_proj_folder.text().strip() or "C:\\",
            QFileDialog.Option.DontUseNativeDialog
        )
        if folder:
            self.txt_proj_folder.setText(folder)

    def _check_selected_model_cached(self):
        model_str = self.combo_model.currentText().split()[0]
        hub_dir = Path.home() / ".cache" / "huggingface" / "hub"
        cached = (hub_dir / f"models--Systran--faster-whisper-{model_str}").exists()
        if cached:
            self.lbl_model_status.setText(f"✅ Модель '{model_str}' уже загружена на вашем ПК и готова к работе!")
            self.lbl_model_status.setStyleSheet("color: #00FFCC; font-weight: bold;")
            self.btn_download_model.setText("🔄 Проверить / перезагрузить модель")
        else:
            self.lbl_model_status.setText("Модель ещё не загружена (будет загружена по кнопке выше или при первой записи).")
            self.lbl_model_status.setStyleSheet("color: #9AA0A6;")
            self.btn_download_model.setText("📥 Загрузить модель в локальный кэш")

    def _start_model_download(self):
        model_str = self.combo_model.currentText().split()[0]
        self.btn_download_model.setEnabled(False)
        self.download_progress.setVisible(True)
        self.lbl_model_status.setText("⏳ Загрузка и проверка модели, пожалуйста подождите...")

        self.download_worker = ModelDownloadWorker(model_str, device=config.get("compute_device", "cpu"))
        self.download_worker.finished_signal.connect(self._on_model_downloaded)
        self.download_worker.start()

    def _on_model_downloaded(self, success: bool, error_msg: str):
        self.download_progress.setVisible(False)
        self.btn_download_model.setEnabled(True)

        if success:
            self._check_selected_model_cached()
        else:
            self.lbl_model_status.setText(f"❌ Ошибка: {error_msg}")
            self.lbl_model_status.setStyleSheet("color: #FF5A5A;")

    def _go_prev(self):
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
            self._update_nav_buttons()

    def _go_next(self):
        idx = self.stack.currentIndex()
        if idx == 0:
            # Сохраняем выбранные аудиоустройства
            config.set("selected_mic", self.combo_mic.currentData() or "")
            config.set("selected_speaker", self.combo_spk.currentData() or "")
            self.stack.setCurrentIndex(1)
            self._update_nav_buttons()

        elif idx == 1:
            name = self.txt_proj_name.text().strip()
            folder = self.txt_proj_folder.text().strip()
            if not name:
                QMessageBox.warning(self, "Ошибка", "Укажите имя проекта.")
                return
            if not folder:
                QMessageBox.warning(self, "Ошибка", "Укажите папку для сохранения отчетов.")
                return

            config.add_project(name, folder)
            self.stack.setCurrentIndex(2)
            self._update_nav_buttons()

        elif idx == 2:
            # Завершение
            model_str = self.combo_model.currentText().split()[0]
            config.set("whisper_model", model_str)
            config.set("first_run", False)

            if self.monitor:
                self.monitor.stop()
                self.monitor.wait()

            self.accept()

    def _update_nav_buttons(self):
        idx = self.stack.currentIndex()
        self.lbl_step.setText(f"Шаг {idx + 1} из 3")
        self.btn_prev.setVisible(idx > 0)
        if idx == 2:
            self.btn_next.setText("🚀 Завершить и начать")
        else:
            self.btn_next.setText("Далее →")

    def closeEvent(self, event):
        if self.monitor:
            self.monitor.stop()
            self.monitor.wait()
        super().closeEvent(event)
