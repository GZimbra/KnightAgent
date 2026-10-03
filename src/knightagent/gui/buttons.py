"""Native ttk buttons with a surface rendered at the actual allocated size.

The image is never stretched or tiled.  A one-pixel image-element request lets
ttk measure the text and padding; Configure then supplies the exact surface.
The native button class bindings still handle commands, keyboard and state.
"""

from itertools import count
import math
import struct
from time import monotonic
import tkinter as tk
from tkinter import ttk
import zlib

from . import theme


_BUTTON_IDS = count(1)


def _rgb(color):
    return tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))


def _mix(start, end, amount):
    return tuple(round(a + (b - a) * amount) for a, b in zip(start, end))


def _chunk(kind, payload):
    return (struct.pack("!I", len(payload)) + kind + payload
            + struct.pack("!I", zlib.crc32(kind + payload) & 0xffffffff))


def rounded_png(width, height, radius, stroke, top, bottom, border, background, gradient_height=None):
    """Rasterize smooth corners over the containing surface, without seams."""
    radius = min(radius, width / 2, height / 2)
    rows = bytearray()
    background_pixel = bytes((*background, 255))
    for y in range(height):
        rows.append(0)  # PNG scanline filter: None.
        extent = height if gradient_height is None else gradient_height
        fill = _mix(top, bottom, min(1, y / max(1, extent - 1)))
        fill_pixel = bytes((*fill, 255))
        dy = max(radius - y - .5, y + .5 - (height - radius), 0)
        # Only the edge strips need per-pixel distance calculations.
        flat_start = min(width, math.ceil(radius + stroke))
        flat_end = max(flat_start, width - flat_start)
        for start, end in ((0, flat_start), (flat_end, width)):
            if start == flat_end and flat_end > flat_start:
                if y + .5 >= stroke and height - y - .5 >= stroke:
                    rows.extend(fill_pixel * (flat_end - flat_start))
                else:
                    coverage = max(0, min(1, min(y + .5, height - y - .5) - stroke + .5))
                    rows.extend(bytes((*_mix(border, fill, coverage), 255)) * (flat_end - flat_start))
            for x in range(start, end):
                dx = max(radius - x - .5, x + .5 - (width - radius), 0)
                distance = math.hypot(dx, dy) - radius
                outer = max(0, min(1, .5 - distance))
                inner = max(0, min(1, .5 - distance - stroke))
                if outer == 0:
                    rows.extend(background_pixel)
                elif inner == 1:
                    rows.extend(fill_pixel)
                else:
                    edge = _mix(border, fill, inner / outer if outer else 0)
                    rows.extend(bytes((*_mix(background, edge, outer), 255)))
    header = struct.pack("!2I5B", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(rows, 2)) + _chunk(b"IEND", b""))


class RoundedButton(ttk.Button):
    """Drop-in ttk.Button supporting default, Accent and Ghost styles."""

    def __init__(self, master=None, **kwargs):
        self._base_style = kwargs.pop("style", "TButton") or "TButton"
        self._style_name = f"KnightButton{next(_BUTTON_IDS)}.{self._base_style}"
        self._render_timer = None
        self._state_timer = None
        self._colors = None
        self._target = None
        self._animation_start = 0.0
        self._animation_origin = None
        self._image_size = (0, 0)
        self._ready = False
        super().__init__(master, style=self._style_name, **kwargs)
        self._style = ttk.Style(self)
        self._scale = max(1.0, self.winfo_fpixels("1i") / 96)
        self._surface_image = tk.PhotoImage(master=self, width=1, height=1)
        element = f"KnightButton{next(_BUTTON_IDS)}.surface"
        self._style.element_create(element, "image", self._surface_image,
                                   width=1, height=1, sticky="nsew")
        self._style.layout(self._style_name, [(element, {
            "sticky": "nsew", "children": [("Button.padding", {
                "sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]
            })]
        })])
        self._configure_style()
        self.bind("<Configure>", self._resize, add=True)
        for sequence in ("<Enter>", "<Leave>", "<ButtonPress-1>", "<ButtonRelease-1>",
                         "<FocusIn>", "<FocusOut>", "<KeyPress-space>", "<KeyRelease-space>"):
            self.bind(sequence, self._queue_state_sync, add=True)
        self.bind("<Destroy>", self._dispose, add=True)
        self._ready = True
        self._queue_state_sync()

    def _configure_style(self):
        family = getattr(theme, "UI_FONT", "Century Gothic")
        if isinstance(family, (tuple, list)):
            family = family[0]
        foreground = theme.BLACK if self._base_style.startswith("Accent") else theme.WHITE
        self._style.configure(self._style_name, font=(family, 12),
                              padding=(round(14 * self._scale), round(9 * self._scale)),
                              foreground=foreground, borderwidth=0, relief="flat", anchor="center")
        # Explicit maps replace any inherited active color inversion.
        self._style.map(self._style_name,
                        foreground=[("disabled", theme.MUTED), ("!disabled", foreground)],
                        background=[], relief=[], bordercolor=[], lightcolor=[], darkcolor=[])

    def configure(self, cnf=None, **kwargs):
        if not getattr(self, "_ready", False):
            return super().configure(cnf, **kwargs)
        options = dict(cnf) if isinstance(cnf, dict) else {}
        options.update(kwargs)
        if "style" in options:
            self._base_style = options["style"] or "TButton"
            options["style"] = self._style_name
            self._configure_style()
        result = super().configure(options) if options else super().configure(cnf, **kwargs)
        if options:
            self._queue_state_sync()
        return result

    config = configure

    def cget(self, key):
        if key == "style":
            return self._base_style
        return super().cget(key)

    def state(self, statespec=None):
        result = super().state(statespec)
        if statespec is not None and getattr(self, "_ready", False):
            self._queue_state_sync()
        return result

    def _parent_color(self):
        parent = self.master
        try:
            if isinstance(parent, ttk.Widget):
                name = parent.cget("style") or parent.winfo_class()
                color = self._style.lookup(name, "background", parent.state())
            else:
                color = parent.cget("background")
            channels = self.winfo_rgb(color or theme.BLACK)
            return tuple(round(channel / 257) for channel in channels)
        except tk.TclError:
            return _rgb(theme.BLACK)

    def _palette(self):
        states = set(super().state())
        surface, orange, white = _rgb(theme.SURFACE), _rgb(theme.ORANGE), _rgb(theme.WHITE)
        background, black = self._parent_color(), _rgb(theme.BLACK)
        accent = self._base_style.startswith("Accent")
        ghost = self._base_style.startswith("Ghost")
        if "disabled" in states:
            top = _mix(background, orange if accent else white, .065 if accent else .025)
            return (top, _mix(top, background, .22), _mix(background, white, .055), background)
        active = "active" in states or "selected" in states
        pressed = "pressed" in states
        if accent:
            top = _mix(orange, black if pressed else white, .065 if pressed else (.09 if active else .035))
            bottom = _mix(orange, black, .10 if pressed else (.015 if active else .055))
            border = _mix(orange, white, .18 if active else .10)
        else:
            base = background if ghost else surface
            if active or pressed:
                top = _mix(base, orange, .065 if active and not pressed else .035)
                bottom = _mix(base, orange, .030 if active and not pressed else .015)
                border = _mix(base, orange, .24 if pressed else .18)
            else:
                top = base if ghost else _mix(base, white, .018)
                bottom = base
                border = base if ghost else _rgb(theme.BORDER)
        if "focus" in states:
            border = _mix(border, orange if not accent else white, .45 if not accent else .28)
        return top, bottom, border, background

    def _queue_state_sync(self, _event=None):
        if self._state_timer is None:
            # Widget events precede ttk class bindings, so inspect state afterwards.
            self._state_timer = self.after_idle(self._sync_state)

    def _sync_state(self):
        self._state_timer = None
        target = self._palette()
        if target == self._target:
            return
        self._target = target
        if self._colors is None or self.instate(("disabled",)):
            self._colors = target
            self._paint()
            return
        self._animation_origin = self._colors
        self._animation_start = monotonic()
        if self._render_timer is not None:
            self.after_cancel(self._render_timer)
        self._animate()

    def _animate(self):
        self._render_timer = None
        progress = min(1, (monotonic() - self._animation_start) / .12)
        amount = 1 - (1 - progress) ** 3
        self._colors = tuple(_mix(a, b, amount) for a, b in zip(self._animation_origin, self._target))
        self._paint()
        if progress < 1:
            self._render_timer = self.after(20, self._animate)

    def _resize(self, event):
        if (event.width, event.height) != self._image_size:
            self._paint()

    def _paint(self):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 2 or height < 2:
            return
        if self._colors is None:
            self._colors = self._target = self._palette()
        self._image_size = width, height
        png = rounded_png(width, height, 10 * self._scale, max(1, self._scale * .75), *self._colors)
        self._surface_image.configure(width=width, height=height, data=png, format="png")

    def _dispose(self, event):
        if event.widget is self:
            for name in ("_render_timer", "_state_timer"):
                timer = getattr(self, name)
                if timer is not None:
                    self.after_cancel(timer)
                    setattr(self, name, None)
