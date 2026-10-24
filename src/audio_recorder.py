import os
import wave
import time
import threading
import warnings
import numpy as np
import soundcard as sc
from pathlib import Path
from src.config import config, get_project_recordings_dir
from src.logger import logger

warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)

def play_beep(is_start: bool = True):
    """Воспроизводит тихий системный звуковой сигнал подтверждения старта/стопа записи"""
    if not config.get("play_sound_signals", True):
        return

    def _beep():
        try:
            import winsound
            if is_start:
                winsound.Beep(880, 130)  # Высокая нота (A5)
            else:
                winsound.Beep(587, 150)  # Низкая нота (D5)
        except Exception:
            pass

    threading.Thread(target=_beep, daemon=True).start()

def get_audio_devices():
    """Возвращает списки доступных имен микрофонов и динамиков"""
    mics = []
    speakers = []
    try:
        for m in sc.all_microphones(include_loopback=False):
            if m.name and m.name not in mics:
                mics.append(m.name)
    except Exception as e:
        logger.warning(f"Ошибка получения списка микрофонов: {e}")

    try:
        for s in sc.all_speakers():
            if s.name and s.name not in speakers:
                speakers.append(s.name)
    except Exception as e:
        logger.warning(f"Ошибка получения списка динамиков: {e}")

    return mics, speakers

def get_active_devices():
    """Возвращает выбранный (или по умолчанию) микрофон и loopback-устройство динамиков"""
    selected_mic_name = config.get("selected_mic", "").strip()
    selected_spk_name = config.get("selected_speaker", "").strip()

    mic = None
    if selected_mic_name:
        try:
            for m in sc.all_microphones(include_loopback=False):
                if m.name == selected_mic_name:
                    mic = m
                    break
        except Exception:
            pass

    if mic is None:
        mic = sc.default_microphone()

    spk = None
    if selected_spk_name:
        try:
            for s in sc.all_speakers():
                if s.name == selected_spk_name:
                    spk = s
                    break
        except Exception:
            pass

    if spk is None:
        spk = sc.default_speaker()

    try:
        loopback = sc.get_microphone(id=spk.id, include_loopback=True)
    except Exception:
        # Fallback на системный loopback по умолчанию
        loopback = sc.get_microphone(id=sc.default_speaker().id, include_loopback=True)

    return mic, loopback

class DualChannelAudioRecorder:
    """
    Захватывает одновременно Микрофон и Системные динамики (WASAPI Loopback)
    в двух параллельных потоках с поддержкой выбора устройств.
    """
    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate
        self.is_recording = False
        self.output_filepath = None
        self.t_mic = None
        self.t_loop = None
        self.mic_frames = []
        self.loop_frames = []

    def start(self, project_name: str = "Default", filename_prefix: str = "audio") -> Path:
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        target_dir = get_project_recordings_dir(project_name)
        self.output_filepath = target_dir / f"{filename_prefix}_{timestamp}.wav"

        self.mic_frames = []
        self.loop_frames = []
        self.is_recording = True

        play_beep(is_start=True)

        self.t_mic = threading.Thread(target=self._record_mic_worker, daemon=True)
        self.t_loop = threading.Thread(target=self._record_loopback_worker, daemon=True)

        self.t_mic.start()
        self.t_loop.start()

        logger.info(f"[AudioRecorder] Запись звука запущена -> {self.output_filepath.name}")
        return self.output_filepath

    def _record_mic_worker(self):
        try:
            mic, _ = get_active_devices()
            block_size = int(self.sample_rate * 0.1)
            with mic.recorder(samplerate=self.sample_rate, channels=1) as r:
                while self.is_recording:
                    try:
                        chunk = r.record(numframes=block_size)
                        chunk_1d = chunk.mean(axis=1) if chunk.ndim > 1 else chunk.ravel()
                        self.mic_frames.append(chunk_1d)
                    except Exception as e:
                        time.sleep(0.05)
        except Exception as e:
            logger.error("[AudioRecorder] Сбой потока микрофона", exc=e)

    def _record_loopback_worker(self):
        try:
            _, loopback = get_active_devices()
            block_size = int(self.sample_rate * 0.1)
            with loopback.recorder(samplerate=self.sample_rate, channels=1) as r:
                while self.is_recording:
                    try:
                        chunk = r.record(numframes=block_size)
                        chunk_1d = chunk.mean(axis=1) if chunk.ndim > 1 else chunk.ravel()
                        self.loop_frames.append(chunk_1d)
                    except Exception as e:
                        time.sleep(0.05)
        except Exception as e:
            logger.error("[AudioRecorder] Сбой потока динамиков", exc=e)

    def stop(self) -> Path:
        self.is_recording = False
        play_beep(is_start=False)

        if self.t_mic and self.t_mic.is_alive():
            self.t_mic.join(timeout=2.0)
        if self.t_loop and self.t_loop.is_alive():
            self.t_loop.join(timeout=2.0)

        mic_full = np.concatenate(self.mic_frames, axis=0) if self.mic_frames else np.zeros(0, dtype=np.float32)
        loop_full = np.concatenate(self.loop_frames, axis=0) if self.loop_frames else np.zeros(0, dtype=np.float32)

        min_len = min(len(mic_full), len(loop_full))
        if min_len == 0:
            min_len = self.sample_rate
            mic_full = np.zeros(min_len, dtype=np.float32)
            loop_full = np.zeros(min_len, dtype=np.float32)
        else:
            mic_full = mic_full[:min_len]
            loop_full = loop_full[:min_len]

        # Авто-усиление микрофона
        mic_full = mic_full * 3.5

        # Нормализация
        max_val = max(np.max(np.abs(mic_full)), np.max(np.abs(loop_full)))
        if max_val > 0.95:
            scale = 0.95 / max_val
            mic_full *= scale
            loop_full *= scale

        stereo_float = np.column_stack((mic_full, loop_full))
        stereo_int16 = (np.clip(stereo_float, -1.0, 1.0) * 32767).astype(np.int16)

        with wave.open(str(self.output_filepath), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(stereo_int16.tobytes())

        logger.info(f"[AudioRecorder] Запись сохранена: {self.output_filepath.name} ({min_len / self.sample_rate:.1f} сек)")
        return self.output_filepath
