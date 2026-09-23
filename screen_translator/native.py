import ctypes
import sys
import winreg
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, Qt

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def allow_set_foreground_window(process_id: int) -> bool:
    """Grant an existing instance permission to foreground its settings window."""
    try:
        return bool(user32.AllowSetForegroundWindow(int(process_id)))
    except (AttributeError, OSError, ValueError):
        return False


def animations_enabled() -> bool:
    """Return the Windows accessibility preference for client-area animation."""
    enabled = wintypes.BOOL()
    try:
        if user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return bool(enabled.value)
    except OSError:
        pass
    return True


def hotkey_parts(sequence):
    # Callers have passed a Config object here by accident. Without this the
    # failure surfaces as an AttributeError from inside an exception handler,
    # which is the worst place to discover a type error.
    if not isinstance(sequence, str):
        raise ValueError("快捷键格式错误")
    parts = sequence.upper().split("+")
    modifiers = 0x4000
    mapping = {"CTRL": 2, "ALT": 1, "SHIFT": 4, "META": 8, "WIN": 8}
    for part in parts[:-1]:
        if part not in mapping:
            raise ValueError("快捷键格式错误")
        modifiers |= mapping[part]
    if len(parts) < 2:
        raise ValueError("请至少包含 Ctrl、Alt 或 Shift 修饰键")
    key = parts[-1]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return modifiers, ord(key)
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return modifiers, 0x70 + int(key[1:]) - 1
    raise ValueError("请使用字母、数字或 F1–F24 组合键")


class Hotkey(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.current = None
        self.key_id = 12001

    def register(self, sequence):
        if sequence == self.current:
            return
        mods, key = hotkey_parts(sequence)
        new_id = 12002 if self.key_id == 12001 else 12001
        if not user32.RegisterHotKey(None, new_id, mods, key):
            raise ValueError("该快捷键已被系统或其他应用占用")
        user32.UnregisterHotKey(None, self.key_id)
        self.key_id, self.current = new_id, sequence

    def close(self):
        user32.UnregisterHotKey(None, self.key_id)

    def nativeEventFilter(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x312 and msg.wParam == self.key_id:
            self.callback()
            return True, 0
        return False, 0


AUTOSTART_FLAG = "--autostart"


def set_startup(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            import subprocess

            args = (
                [sys.executable]
                if getattr(sys, "frozen", False)
                else [sys.executable, "-m", "screen_translator.app"]
            )
            # Say why the process is starting instead of leaving it to be
            # inferred: a login launch must stay in the tray even when the
            # installation is not usable yet.
            args.append(AUTOSTART_FLAG)
            winreg.SetValueEx(key, "ScreenTranslator", 0, winreg.REG_SZ, subprocess.list2cmdline(args))
        else:
            try:
                winreg.DeleteValue(key, "ScreenTranslator")
            except FileNotFoundError:
                pass


class Job:
    """KILL_ON_JOB_CLOSE also cleans up children after an application crash."""

    def __init__(self):
        class Basic(ctypes.Structure):
            _fields_ = [
                ("time1", ctypes.c_int64),
                ("time2", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("min", ctypes.c_size_t),
                ("max", ctypes.c_size_t),
                ("count", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [(str(i), ctypes.c_uint64) for i in range(6)]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", IO),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = kernel32.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x2000
        if not self.handle or not kernel32.SetInformationJobObject(
            self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def attach(self, process):
        if not kernel32.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            process.kill()
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None


def app_theme_is_light() -> bool:
    """Whether Windows is asking applications to use a light appearance.

    `AppsUseLightTheme` is the per-application setting, distinct from
    `SystemUsesLightTheme` which governs the taskbar and Start menu. A
    user can and often does set them differently, and following the
    wrong one produces an application that disagrees with every other
    one on the desktop.

    Defaults to light when the value is missing, which is Windows 10
    before the setting existed.
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except (OSError, ValueError):
        return True


# DwmSetWindowAttribute. 38 is DWMWA_SYSTEMBACKDROP_TYPE, which exists
# from Windows 11 22H2; 20 is DWMWA_USE_IMMERSIVE_DARK_MODE, which the
# title bar needs so it does not stay light behind a dark window.
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_MAINWINDOW = 2


def _set_window_attribute(handle: int, attribute: int, value: int) -> bool:
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
    except OSError:
        return False
    data = ctypes.c_int(value)
    result = dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(handle), ctypes.c_uint(attribute), ctypes.byref(data), ctypes.sizeof(data)
    )
    # A non-zero HRESULT here means the attribute is unknown to this
    # build of Windows, which is the expected answer on 10 and on early
    # 11. Nothing is broken; the window is simply opaque.
    return result == 0


def apply_window_material(window, *, dark: bool) -> bool:
    """Ask DWM for the Mica backdrop. Harmless where it is unavailable.

    The closest thing Windows has to the translucent material the visual
    direction is modelled on, and the only one reachable without a
    background filter Qt does not have. It is window-level rather than
    element-level, which is stated in ADR 0002 rather than implied.

    The native title bar is kept; Mica does not require drawing our own,
    and drawing our own would break the rule that says keep it.
    """
    handle = int(window.winId())
    if not handle:
        return False
    # Order matters: the title bar has to be told about dark mode
    # separately, or it stays light above a dark window.
    _set_window_attribute(handle, _DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark))
    applied = _set_window_attribute(handle, _DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_MAINWINDOW)
    if applied:
        # Mica shows through only where nothing opaque is painted.
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    return applied
