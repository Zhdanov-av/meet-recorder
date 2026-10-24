import os
import time
import wave
import numpy as np
from pathlib import Path
from src.config import config, get_project_recordings_dir
from src.logger import logger

def format_timestamp(seconds: float) -> str:
    """Форматирует секунды в виде [HH:MM:SS]"""
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"

class Transcriber:
    def __init__(self):
        self.model = None
        self.current_model_size = None
        self.current_device = None

    def load_model(self, model_size: str = None):
        if model_size is None:
            model_size = config.get("whisper_model", "medium")

        target_device = config.get("compute_device", "cpu").lower()

        if self.model is None or self.current_model_size != model_size or self.current_device != target_device:
            logger.info(f"[Transcriber] Инициализация локальной модели Faster-Whisper '{model_size}' ({target_device})...")
            from faster_whisper import WhisperModel
            
            try:
                if target_device == "cuda":
                    try:
                        self.model = WhisperModel(model_size, device="cuda", compute_type="float16")
                        self.current_device = "cuda"
                        logger.info(f"[Transcriber] Модель '{model_size}' загружена на GPU (CUDA float16)")
                    except Exception as cuda_err:
                        logger.warning(f"[Transcriber] Не удалось запустить на CUDA ({cuda_err}), переключение на CPU...")
                        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
                        self.current_device = "cpu"
                else:
                    self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
                    self.current_device = "cpu"
                    logger.info(f"[Transcriber] Модель '{model_size}' готова к работе (CPU int8)")

            except Exception as e:
                logger.error(f"[Transcriber] Ошибка загрузки модели '{model_size}'", exc=e)
                raise e

            self.current_model_size = model_size

    def _determine_speaker(self, audio_data: np.ndarray, sample_rate: int, start_sec: float, end_sec: float) -> str:
        """
        Анализирует двухканальный аудиопоток на отрезке [start_sec, end_sec]:
        - CH1 (Левый) = Микрофон (Вы)
        - CH2 (Правый) = Системные динамики (Участники встречи)
        """
        if audio_data is None or len(audio_data) == 0:
            return "Участники встречи"

        start_idx = int(start_sec * sample_rate)
        end_idx = int(end_sec * sample_rate)
        
        if start_idx >= len(audio_data):
            return "Участники встречи"
            
        segment = audio_data[start_idx:end_idx]

        if len(segment) == 0:
            return "Участники встречи"

        if segment.ndim == 2 and segment.shape[1] >= 2:
            mic_energy = np.mean(np.abs(segment[:, 0]))
            sys_energy = np.mean(np.abs(segment[:, 1]))

            if mic_energy > sys_energy * 1.2:
                return "Вы"
            elif sys_energy > mic_energy * 1.2:
                return "Участники встречи"

        return "Участники встречи"

    def transcribe_and_save(self, audio_path: Path, project_name: str, meeting_title: str = "") -> Path:
        """
        Транскрибирует аудиозапись встречи и сохраняет Markdown протокол (.md) в папку проекта.
        Имя файла: '<Название встречи> - ЧЧ.ММ ДД.ММ.ГГГГ.md'
        """
        self.load_model()

        projects_dict = config.get("projects", {})
        project_folder = projects_dict.get(project_name)

        if not project_folder or not Path(project_folder).exists():
            project_folder = str(get_project_recordings_dir(project_name))

        target_dir = Path(project_folder)
        target_dir.mkdir(parents=True, exist_ok=True)

        date_file_str = time.strftime("%H.%M %d.%m.%Y")
        date_display = time.strftime("%d.%m.%Y %H:%M")
        
        raw_title = meeting_title.strip() if meeting_title and meeting_title.strip() else "Встреча"
        # Удаляем запрещенные символы Windows для имени файла
        safe_title = "".join(c for c in raw_title if c not in r':*?"<>|\/').strip()
        if not safe_title:
            safe_title = "Встреча"

        md_filename = f"{safe_title} - {date_file_str}.md"
        output_md_path = target_dir / md_filename

        logger.info(f"[Transcriber] Распознавание речи из файла: {audio_path.name}...")

        duration_str = "00:00:00"
        audio_data = None
        sample_rate = 44100

        try:
            if audio_path.exists():
                with wave.open(str(audio_path), "rb") as wf:
                    sample_rate = wf.getframerate()
                    nchannels = wf.getnchannels()
                    frames = wf.readframes(wf.getnframes())
                    raw_arr = np.frombuffer(frames, dtype=np.int16)
                    
                    if nchannels > 1:
                        audio_data = raw_arr.reshape(-1, nchannels)
                    else:
                        audio_data = raw_arr
                    
                    dur_secs = len(raw_arr) / float(sample_rate * nchannels)
                    duration_str = format_timestamp(dur_secs)
        except Exception as e:
            logger.warning(f"[Transcriber] Предупреждение чтения аудиофайла: {e}")

        segments_list = []
        try:
            if audio_path.exists():
                segments, info = self.model.transcribe(
                    str(audio_path),
                    language="ru",
                    beam_size=5,
                    vad_filter=True
                )
                segments_list = list(segments)
        except Exception as e:
            logger.error("[Transcriber] Ошибка транскрибации Faster-Whisper", exc=e)

        transcript_blocks = []
        current_speaker = None
        current_text_parts = []
        block_start_time = "00:00"

        for segment in segments_list:
            text = segment.text.strip()
            if not text:
                continue

            speaker = self._determine_speaker(audio_data, sample_rate, segment.start, segment.end)

            if speaker != current_speaker:
                if current_text_parts:
                    transcript_blocks.append(f"**[{block_start_time}] {current_speaker}**:\n" + " ".join(current_text_parts) + "\n\n")
                current_speaker = speaker
                current_text_parts = [text]
                block_start_time = format_timestamp(segment.start)
            else:
                current_text_parts.append(text)

        if current_text_parts:
            transcript_blocks.append(f"**[{block_start_time}] {current_speaker}**:\n" + " ".join(current_text_parts) + "\n\n")

        retention_days = config.get("retention_days", 7)
        md_content = f"""# Протокол встречи: {project_name} - {safe_title}

**Дата и время**: {date_display}  
**Проект**: {project_name}  
**Длительность**: {duration_str}  
**Файл аудиозаписи**: `{audio_path.name}` *(хранится {retention_days} дней)*  

---

## 🗣️ Транскрипция встречи

{"".join(transcript_blocks) if transcript_blocks else "_Речь не обнаружена._"}
"""

        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        logger.info(f"[Transcriber] Протокол встречи (.md) сохранен: {output_md_path}")
        return output_md_path

transcriber = Transcriber()
