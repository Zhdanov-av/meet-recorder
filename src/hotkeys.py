import ctypes
import threading
from ctypes import wintypes
from PySide6.QtCore import QObject, Signal
from src.config import config
from src.logger import logger

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
HOTKEY_ID = 1001

VK_MAPPING = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "escape": 0x1B
}

def parse_hotkey(hotkey_str: str):
    """
    Парсит строку хоткея вида '<ctrl>+<alt>+z' или 'ctrl+alt+z'
    в (modifiers, vk_code).
    """
    clean = hotkey_str.lower().replace("<", "").replace(">", "").strip()
    parts = [p.strip() for p in clean.split("+")]

    mods = 0
    vk = 0x5A  # по умолчанию Z

    for p in parts:
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p in ("alt",):
            mods |= MOD_ALT
        elif p in ("shift",):
            mods |= MOD_SHIFT
        elif p in ("win", "windows", "cmd"):
            mods |= MOD_WIN
        elif p in VK_MAPPING:
            vk = VK_MAPPING[p]
        elif len(p) == 1:
            vk = ord(p.upper())

    return mods, vk

class NativeWindowsHotkeyListener(QObject):
    hotkey_triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_running = False
        self.thread = None
        self.current_hotkey_str = config.get("hotkey", "<ctrl>+<alt>+z")
        self.pynput_listener = None

    def start(self):
        self.is_running = True
        self.current_hotkey_str = config.get("hotkey", "<ctrl>+<alt>+z")
        self.thread = threading.Thread(target=self._run_native_listener, daemon=True)
        self.thread.start()
        logger.info(f"[Hotkey] Слушатель глобального хоткея '{self.current_hotkey_str}' запущен")

    def update_hotkey(self, new_hotkey: str):
        """Перезапускает слушатель с новым сочетанием клавиш"""
        logger.info(f"[Hotkey] Обновление хоткея: '{self.current_hotkey_str}' -> '{new_hotkey}'")
        self.stop()
        config.set("hotkey", new_hotkey)
        self.start()

    def _run_native_listener(self):
        user32 = ctypes.windll.user32
        mods, vk = parse_hotkey(self.current_hotkey_str)

        if not user32.RegisterHotKey(None, HOTKEY_ID, mods, vk):
            logger.warning(f"[Hotkey] Не удалось зарегистрировать '{self.current_hotkey_str}' через RegisterHotKey. Запуск резервного pynput...")
            self._fallback_pynput()
            return

        msg = wintypes.MSG()
        try:
            while self.is_running:
                res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if res <= 0:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.hotkey_triggered.emit()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def _fallback_pynput(self):
        try:
            from pynput import keyboard
            def on_activate():
                self.hotkey_triggered.emit()

            clean_str = self.current_hotkey_str
            if not clean_str.startswith("<") and not clean_str.endswith(">"):
                # Приводим к формату pynput
                parts = clean_str.lower().split("+")
                clean_str = "+".join([f"<{p}>" if len(p) > 1 else p for p in parts])

            hotkey_map = {clean_str: on_activate}
            self.pynput_listener = keyboard.GlobalHotKeys(hotkey_map)
            self.pynput_listener.start()
        except Exception as e:
            logger.error(f"[Hotkey] Ошибка резервного pynput-слушателя: {e}")

    def stop(self):
        self.is_running = False
        try:
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            ctypes.windll.user32.PostQuitMessage(0)
        except Exception:
            pass
        if self.pynput_listener:
            try:
                self.pynput_listener.stop()
            except Exception:
                pass

GlobalHotkeyListener = NativeWindowsHotkeyListener
