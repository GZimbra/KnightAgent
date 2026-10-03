"""Packaged Knight Agent artwork for Tk and the native Windows application icon."""

from pathlib import Path
import sys
import tkinter as tk


ASSETS = Path(__file__).with_name("assets")
LOGO_WIDTHS = (220, 275, 330, 385, 440, 550, 660)
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
APP_NAME = "Knight Agent"


def sidebar_logo(master, scale=1.0):
    """Use an antialiased asset matching the display density without enlargement."""
    target = round(220 * scale)
    width = max((width for width in LOGO_WIDTHS if width <= target), default=220)
    return tk.PhotoImage(master=master, file=str(ASSETS / f"knight-agent-logo-{width}.png"))


def apply_app_icon(window, *, default=False):
    # PhotoImage handles must live as long as the window. default=True also
    # covers future dialogs owned by the same Tk interpreter.
    images = tuple(tk.PhotoImage(master=window, file=str(ASSETS / f"knight-agent-icon-{size}.png"))
                   for size in ICON_SIZES)
    window._knight_icon_images = images
    window.iconphoto(default, *images)
    if sys.platform == "win32":
        # ICO carries the native small/large icon family used by Windows.
        window.iconbitmap(str(ASSETS / "knight-agent.ico"))
