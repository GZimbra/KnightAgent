"""Use the installed Knightec Group typeface without redistributing font files."""

from tkinter import font as tkfont

BRAND_FONT = "Century Gothic"


def configure_fonts(root):
    families = {name.casefold(): name for name in tkfont.families(root=root)}
    # The brand font is installed on the target Windows computer. Keep the app
    # usable on machines without it; the README documents this fallback.
    for name in (BRAND_FONT, "Segoe UI", "Arial"):
        if name.casefold() in families:
            return families[name.casefold()]
    return tkfont.nametofont("TkDefaultFont", root=root).actual("family")
