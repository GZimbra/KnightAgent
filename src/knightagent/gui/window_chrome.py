"""Native Windows title bars that follow the application's dark palette."""

import ctypes
from ctypes import wintypes
import sys
import tkinter as tk


APP_USER_MODEL_ID = "Digitec.KnightAgent.Desktop"


def configure_app_identity() -> bool:
    """Give the taskbar an application identity; call before creating Tk."""
    if sys.platform != "win32":
        return False
    try:
        set_identity = ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID
        set_identity.argtypes = [wintypes.LPCWSTR]
        set_identity.restype = ctypes.c_long
        return set_identity(APP_USER_MODEL_ID) >= 0
    except (AttributeError, OSError):
        return False


def _apply_native_chrome(window) -> bool:
    """Apply supported DWM attributes without replacing the native frame."""
    try:
        if not window.winfo_exists():
            return False
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_ancestor = user32.GetAncestor
        get_ancestor.argtypes = [wintypes.HWND, wintypes.UINT]
        get_ancestor.restype = wintypes.HWND
        # Tk exposes its client HWND. GA_ROOT finds this window's native frame,
        # while GA_ROOTOWNER would incorrectly target an owned dialog's parent.
        hwnd = get_ancestor(window.winfo_id(), 2)
        if not hwnd:
            return False
        set_attribute = ctypes.WinDLL("dwmapi").DwmSetWindowAttribute
        set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD]
        set_attribute.restype = ctypes.c_long

        # BOOL and COLORREF are 32-bit values. Symmetric RGB values below are
        # also their COLORREF (0x00BBGGRR) equivalents.
        attributes = (
            (20, wintypes.BOOL(1)),             # DWMWA_USE_IMMERSIVE_DARK_MODE
            (34, wintypes.DWORD(0x080808)),     # DWMWA_BORDER_COLOR
            (35, wintypes.DWORD(0x080808)),     # DWMWA_CAPTION_COLOR
            (36, wintypes.DWORD(0xF5F5F5)),     # DWMWA_TEXT_COLOR
        )
        applied = False
        for attribute, value in attributes:
            result = set_attribute(hwnd, attribute, ctypes.byref(value),
                                   ctypes.sizeof(value))
            # Older Windows versions may reject newer attributes. Continue so
            # each supported attribute can still be applied independently.
            applied = result >= 0 or applied
        return applied
    except (AttributeError, OSError, tk.TclError):
        return False


def apply_window_chrome(window) -> None:
    """Style a Tk or Toplevel now and whenever its native frame is remapped.

    Call on the Tk thread after creating the window. Unsupported platforms
    retain their normal native frame. Repeated calls do not duplicate bindings.
    """
    if sys.platform != "win32":
        return
    if getattr(window, "_knightagent_chrome_binding", None):
        return

    def cancel_pending():
        pending = getattr(window, "_knightagent_chrome_after", None)
        window._knightagent_chrome_after = None
        if pending is not None:
            try:
                window.after_cancel(pending)
            except tk.TclError:
                pass

    def apply_when_idle():
        window._knightagent_chrome_after = None
        _apply_native_chrome(window)

    def on_map(event):
        # Toplevel bind tags also receive Map events from their child widgets.
        if event.widget is window:
            cancel_pending()
            _apply_native_chrome(window)

    def on_destroy(event):
        if event.widget is window:
            cancel_pending()

    try:
        window._knightagent_chrome_binding = window.bind("<Map>", on_map, add="+")
        window._knightagent_chrome_destroy_binding = window.bind("<Destroy>", on_destroy, add="+")
        window._knightagent_chrome_after = window.after_idle(apply_when_idle)
    except tk.TclError:
        # A queued settings-window creation may be cancelled during shutdown.
        pass
