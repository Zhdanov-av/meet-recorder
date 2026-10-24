import time
import subprocess
import threading
from pathlib import Path
from src.config import get_project_recordings_dir

class ScreenVideoRecorder:
    """
    Захватывает экран в формате MP4 с точным совпадением реальной скорости видео и аудио 1:1.
    """
    def __init__(self, fps: int = 20):
        self.fps = fps
        self.is_recording = False
        self.thread = None
        self.output_filepath = None
        self.temp_video_filepath = None

    def start(self, project_name: str = "Default", filename_prefix: str = "video") -> Path:
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        target_dir = get_project_recordings_dir(project_name)
        
        self.temp_video_filepath = target_dir / f"temp_{filename_prefix}_{timestamp}.mp4"
        self.output_filepath = target_dir / f"{filename_prefix}_{timestamp}.mp4"

        self.is_recording = True
        self.thread = threading.Thread(target=self._record_loop, daemon=True)
        self.thread.start()
        print(f"[VideoRecorder] Запись экрана в нормальной скорости (20 FPS) запущена -> {self.temp_video_filepath.name}")
        return self.output_filepath

    def _record_loop(self):
        try:
            import mss
            import numpy as np
            import imageio_ffmpeg

            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

            with mss.mss() as sct:
                monitor = sct.monitors[1]
                width = monitor["width"]
                height = monitor["height"]

                if width % 2 != 0: width -= 1
                if height % 2 != 0: height -= 1

                cmd = [
                    ffmpeg_exe,
                    "-y",
                    "-f", "rawvideo",
                    "-vcodec", "rawvideo",
                    "-s", f"{width}x{height}",
                    "-pix_fmt", "bgra",
                    "-r", str(self.fps),
                    "-i", "-",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "ultrafast",
                    "-tune", "zerolatency",
                    str(self.temp_video_filepath)
                ]

                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                frame_interval = 1.0 / self.fps
                next_frame_time = time.time()

                while self.is_recording:
                    now = time.time()
                    if now >= next_frame_time:
                        img = sct.grab(monitor)
                        raw_bytes = bytes(img.raw)
                        try:
                            proc.stdin.write(raw_bytes)
                        except Exception:
                            break
                        next_frame_time += frame_interval
                    else:
                        time.sleep(max(0, next_frame_time - now))

                proc.stdin.close()
                proc.wait()

        except Exception as e:
            print(f"[VideoRecorder] Ошибка записи видео: {e}")

    def stop_and_mux_audio(self, audio_wav_path: Path) -> Path:
        """Сводит видеоряда и аудиопоток без изменения скорости воспроизведения"""
        self.is_recording = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3.0)

        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

            if self.temp_video_filepath.exists() and audio_wav_path and audio_wav_path.exists():
                print(f"[VideoRecorder] Сведение видео и аудио 1:1 без ускорения: {self.output_filepath.name}...")
                cmd = [
                    ffmpeg_exe,
                    "-y",
                    "-i", str(self.temp_video_filepath),
                    "-i", str(audio_wav_path),
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    str(self.output_filepath)
                ]
                res = subprocess.run(cmd, capture_output=True)
                if res.returncode == 0 and self.output_filepath.exists():
                    print(f"[VideoRecorder] Готовое видео в 100% реальной скорости создано: {self.output_filepath.name}")
                    try:
                        self.temp_video_filepath.unlink()
                    except Exception:
                        pass
                    return self.output_filepath
        except Exception as e:
            print(f"[VideoRecorder] Ошибка сведения: {e}")

        if self.temp_video_filepath.exists():
            try:
                self.temp_video_filepath.rename(self.output_filepath)
            except Exception:
                pass
        return self.output_filepath
