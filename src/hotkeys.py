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
WM_QUIT = 0x0012
HOTKEY_ID = 1001

VK_MAPPING = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "escape": 0x1B,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22
}

def parse_hotkey(hotkey_str: str):
    """
    Парсит строку хоткея вида '<ctrl>+<alt>+z' или 'ctrl+alt+z'
    в (modifiers, vk_code). Возвращает (mods, vk) или (None, None) при ошибке.
    """
    if not hotkey_str:
        return 0, 0x5A

    clean = hotkey_str.lower().replace("<", "").replace(">", "").strip()
    parts = [p.strip() for p in clean.split("+") if p.strip()]

    if not parts:
        return 0, 0x5A

    mods = 0
    vk = None

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

    if vk is None:
        # Если была указана только модификаторная клавиша или неизвестная строка
        vk = 0x5A  # по умолчанию Z

    return mods, vk

def format_hotkey_display(hotkey_str: str) -> str:
    """Форматирует строку вида '<ctrl>+<alt>+z' в читаемый вид 'Ctrl + Alt + Z'"""
    if not hotkey_str:
        return "Ctrl + Alt + Z"
    clean = hotkey_str.replace("<", "").replace(">", "").strip()
    parts = [p.strip() for p in clean.split("+") if p.strip()]
    formatted = []
    for p in parts:
        p_lower = p.lower()
        if p_lower in ("ctrl", "control"):
            formatted.append("Ctrl")
        elif p_lower == "alt":
            formatted.append("Alt")
        elif p_lower == "shift":
            formatted.append("Shift")
        elif p_lower in ("win", "windows"):
            formatted.append("Win")
        else:
            formatted.append(p.upper())
    return " + ".join(formatted)

class NativeWindowsHotkeyListener(QObject):
    hotkey_triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_running = False
        self.thread = None
        self.thread_id = None
        self.current_hotkey_str = config.get("hotkey", "<ctrl>+<alt>+z")
        self.pynput_listener = None

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.current_hotkey_str = config.get("hotkey", "<ctrl>+<alt>+z")
        self.thread = threading.Thread(target=self._run_native_listener, daemon=True)
        self.thread.start()
        logger.info(f"[Hotkey] Слушатель глобального хоткея '{self.current_hotkey_str}' запущен")

    def update_hotkey(self, new_hotkey: str):
        """Безопасно перезапускает слушатель с новым сочетанием клавиш БЕЗ вылета приложения"""
        logger.info(f"[Hotkey] Обновление хоткея: '{self.current_hotkey_str}' -> '{new_hotkey}'")
        self.stop()
        config.set("hotkey", new_hotkey)
        self.start()

    def _run_native_listener(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()

        mods, vk = parse_hotkey(self.current_hotkey_str)

        if not user32.RegisterHotKey(None, HOTKEY_ID, mods, vk):
            logger.warning(f"[Hotkey] Не удалось зарегистрировать '{self.current_hotkey_str}' через RegisterHotKey. Пробуем pynput...")
            self._fallback_pynput()
            return

        msg = wintypes.MSG()
        try:
            while self.is_running:
                res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if res <= 0 or not self.is_running:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.hotkey_triggered.emit()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            logger.error(f"[Hotkey] Ошибка в цикле сообщений: {e}")
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def _fallback_pynput(self):
        try:
            from pynput import keyboard
            def on_activate():
                self.hotkey_triggered.emit()

            clean_str = self.current_hotkey_str
            if not clean_str.startswith("<") and not clean_str.endswith(">"):
                parts = clean_str.lower().split("+")
                clean_str = "+".join([f"<{p}>" if len(p) > 1 else p for p in parts])

            hotkey_map = {clean_str: on_activate}
            self.pynput_listener = keyboard.GlobalHotKeys(hotkey_map)
            self.pynput_listener.start()
        except Exception as e:
            logger.error(f"[Hotkey] Ошибка резервного pynput-слушателя: {e}")

    def stop(self):
        self.is_running = False
        user32 = ctypes.windll.user32

        # Снимаем регистрацию хоткея
        try:
            user32.UnregisterHotKey(None, HOTKEY_ID)
        except Exception:
            pass

        # Отправляем WM_QUIT СТРОГО в фоновый поток (НЕ в GUI поток!)
        if self.thread_id:
            try:
                user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass

        if self.pynput_listener:
            try:
                self.pynput_listener.stop()
            except Exception:
                pass

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.6)
            self.thread = None
            self.thread_id = None

GlobalHotkeyListener = NativeWindowsHotkeyListener
