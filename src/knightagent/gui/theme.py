"""Warm tonal palette and native gradients, derived from black, orange and white."""

import math
from time import monotonic
import tkinter as tk
from tkinter import ttk

BLACK = "#080808"
WHITE = "#f5f5f5"
ORANGE = "#ff8b36"
SIDEBAR = "#000000"
SURFACE = "#14110f"
USER_SURFACE = "#20170f"
BORDER = "#34251b"
MUTED = "#bfb7b1"
FLOW_SURFACE = "#110f0d"
UI_FONT = "Segoe UI"


def blend(start, end, amount):
    a = tuple(int(start[i:i+2], 16) for i in (1, 3, 5))
    b = tuple(int(end[i:i+2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y-x)*amount):02x}" for x, y in zip(a, b))


def apply_theme(root):
    global UI_FONT
    from tkinter import font as tkfont
    from .typography import configure_fonts
    UI_FONT = configure_fonts(root)
    scale = max(1.0, root.winfo_fpixels("1i") / 96)
    root.configure(bg=BLACK)
    root.option_add("*Font", (UI_FONT, 12))
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
        tkfont.nametofont(name, root=root).configure(family=UI_FONT, size=12)
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", WHITE)
    root.option_add("*TCombobox*Listbox.selectBackground", "#3a2515")
    root.option_add("*TCombobox*Listbox.selectForeground", WHITE)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BLACK, foreground=WHITE, font=(UI_FONT, 12),
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    troughcolor=BLACK, focuscolor=ORANGE)
    for name, color in (("TFrame", BLACK), ("Sidebar.TFrame", SIDEBAR),
                        ("Surface.TFrame", SURFACE), ("User.TFrame", USER_SURFACE),
                        ("Flow.TFrame", FLOW_SURFACE), ("Section.TFrame", SURFACE)):
        style.configure(name, background=color)
    for name, background, foreground in (
            ("TLabel", BLACK, WHITE), ("Muted.TLabel", BLACK, MUTED),
            ("Status.TLabel", BLACK, ORANGE), ("Sidebar.TLabel", SIDEBAR, WHITE),
            ("SidebarMuted.TLabel", SIDEBAR, MUTED), ("Surface.TLabel", SURFACE, WHITE),
            ("User.TLabel", USER_SURFACE, WHITE), ("Flow.TLabel", FLOW_SURFACE, WHITE),
            ("Section.TLabel", SURFACE, WHITE)):
        style.configure(name, background=background, foreground=foreground)
    style.configure("Title.TLabel", font=(UI_FONT, 26, "bold"))
    style.configure("TEntry", fieldbackground=BLACK, foreground=WHITE,
                    insertcolor=ORANGE, padding=round(8*scale))
    style.map("TEntry", bordercolor=[("focus", "#b9662c")],
              lightcolor=[("focus", "#b9662c")], darkcolor=[("focus", "#b9662c")])
    style.configure("TCombobox", fieldbackground=BLACK, background=SURFACE, foreground=WHITE,
                    arrowcolor=ORANGE, padding=round(7*scale))
    style.map("TCombobox", fieldbackground=[("readonly", BLACK)],
              foreground=[("readonly", WHITE)], selectbackground=[("!disabled", "#3a2515")],
              selectforeground=[("!disabled", WHITE)], background=[("active", "#241a12")])
    for prefix, background in (("", BLACK), ("Section.", SURFACE)):
        for kind in ("TCheckbutton", "TRadiobutton"):
            name = prefix+kind
            style.configure(name, background=background, foreground=WHITE,
                            indicatorbackground=BLACK, indicatorforeground=ORANGE,
                            indicatorsize=round(13*scale), focuscolor=background)
            style.map(name, background=[("active", background), ("disabled", background)],
                      foreground=[("disabled", MUTED)],
                      indicatorbackground=[("selected", ORANGE), ("!selected", BLACK)])
    for name in ("TLabelframe", "Section.TLabelframe"):
        style.configure(name, background=SURFACE, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, borderwidth=1)
        style.configure(name+".Label", background=SURFACE, foreground=ORANGE,
                        font=(UI_FONT, 13, "bold"))
    style.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {
        "sticky": "ns", "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    style.configure("Vertical.TScrollbar", background=BORDER, width=round(5*scale),
                    arrowsize=0, borderwidth=0, relief="flat", bordercolor=BLACK,
                    lightcolor=BORDER, darkcolor=BORDER)
    style.map("Vertical.TScrollbar", background=[("active", "#82502b")])
    # Native fallback. Application buttons use RoundedButton's full-size renderer.
    style.configure("TButton", padding=(round(14*scale), round(9*scale)),
                    background=SURFACE, foreground=WHITE, font=(UI_FONT, 12),
                    borderwidth=0, relief="flat", focuscolor=SURFACE)
    style.map("TButton", background=[("active", "#261b13"), ("pressed", "#20170f")],
              foreground=[("disabled", MUTED)])
    style.configure("Accent.TButton", background=ORANGE, foreground=BLACK)
    style.configure("Ghost.TButton", background=SIDEBAR)
    style.layout("SettingsNav.TRadiobutton", [("Radiobutton.padding", {
        "sticky": "nswe", "children": [("Radiobutton.focus", {
            "sticky": "nswe", "children": [("Radiobutton.label", {"sticky": "nswe"})]})]})])
    style.configure("SettingsNav.TRadiobutton", background=BLACK, foreground=MUTED,
                    padding=(16, 13), font=(UI_FONT, 12), anchor="w", focuscolor=ORANGE)
    style.map("SettingsNav.TRadiobutton",
              background=[("selected", USER_SURFACE), ("active", SURFACE)],
              foreground=[("selected", ORANGE), ("active", WHITE)])


class ThinkingOrb(tk.Canvas):
    """A quiet white point cloud that warms to orange during actual work."""

    def __init__(self, parent, size=190):
        super().__init__(parent, width=size, height=size, bg=BLACK,
                         highlightthickness=0, borderwidth=0)
        self.size = size
        self.phase = 0.0
        self.active = False
        self.last_frame = monotonic()
        self.timer = None
        self._warmth = 0.0
        self._settle_timer = None
        # Leave the canvas transparent in appearance: depth comes from the
        # points themselves, without the old brown disc behind the sphere.
        self.orbits = []
        for ratio in (.405, .44):
            inset = size*(.5-ratio)
            self.orbits.append(self.create_arc(inset, inset, size-inset, size-inset,
                                               style="arc", outline=blend(BLACK, WHITE, .09),
                                               width=1, start=0, extent=38, state="hidden"))
        self.dots = []
        # A Fibonacci distribution avoids rigid latitude rows and clumps at
        # the poles, preserving a round silhouette at every rotation angle.
        count = 510
        golden_angle = math.pi * (3 - math.sqrt(5))
        for index in range(count):
            y = 1 - 2 * (index + .5) / count
            radius = math.sqrt(1 - y * y)
            angle = index * golden_angle
            item = self.create_oval(0, 0, 0, 0, outline="")
            self.dots.append((item, radius * math.cos(angle), y, radius * math.sin(angle)))
        self._draw()
        self.bind("<Destroy>", self._destroy)

    def _draw(self):
        breath = 1 + .018 * math.sin(self.phase * 2.2) * self._warmth
        for index, orbit in enumerate(self.orbits):
            self.itemconfigure(orbit, state="normal" if self.active else "hidden",
                               start=(self.phase * 52 * (1 if index == 0 else -1) + index * 180) % 360,
                               extent=32 + 9 * math.sin(self.phase + index),
                               outline=blend(BLACK, blend(WHITE, ORANGE, self._warmth),
                                             .08 + .05 * self._warmth))
        cosine, sine = math.cos(self.phase), math.sin(self.phase)
        tilt = .24 + .035 * math.sin(self.phase * .6) * self._warmth
        tilt_cosine, tilt_sine = math.cos(tilt), math.sin(tilt)
        for item, x, y, z in self.dots:
            xx = x * cosine + z * sine
            zz = -x * sine + z * cosine
            yy = y * tilt_cosine - zz * tilt_sine
            depth = y * tilt_sine + zz * tilt_cosine
            perspective = 3.6 / (3.6 - depth)
            cx = self.size / 2 + xx * self.size * .335 * perspective * breath
            cy = self.size / 2 - yy * self.size * .335 * perspective * breath
            front = (depth + 1) / 2
            r = (.48 + .91 * front ** 1.3) * self.size / 190
            self.coords(item, cx-r, cy-r, cx+r, cy+r)
            # All resting points belong to the white/black ramp. While busy,
            # a soft moving highlight varies the orange without hard flashes.
            wave = (.5 + .5 * math.sin(yy * 3.4 - self.phase * 2.8)) ** 3
            orange_amount = self._warmth * (.82 + .18 * wave)
            hue = blend(WHITE, ORANGE, orange_amount)
            luminance = .18 + .80 * front ** 1.45
            luminance = min(1, luminance + wave * self._warmth * .07)
            color = blend(BLACK, hue, luminance)
            self.itemconfigure(item, fill=color)

    def set_active(self, active):
        self.active = bool(active)
        if self._settle_timer is not None:
            self.after_cancel(self._settle_timer)
            self._settle_timer = None
        if active and self.timer is None:
            self.last_frame = monotonic()
            self._tick()
        elif not active and self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        if not active:
            self.last_frame = monotonic()
            self._draw()
            if self._warmth > 0:
                self._settle_timer = self.after(16, self._settle)

    def _tick(self):
        now = monotonic()
        elapsed = max(0, min(.08, now-self.last_frame))
        self.phase += elapsed * .38
        self._warmth += (1 - self._warmth) * min(1, elapsed / .14)
        self.last_frame = now
        self._draw()
        self.timer = self.after(16, self._tick)

    def _settle(self):
        """Finish a short color fade, then leave no idle animation running."""
        self._settle_timer = None
        now = monotonic()
        elapsed = max(0, min(.08, now - self.last_frame))
        self.last_frame = now
        self._warmth = max(0, self._warmth - elapsed / .24)
        self._draw()
        if self._warmth > 0:
            self._settle_timer = self.after(16, self._settle)

    def _destroy(self, event):
        if event.widget is self:
            for attribute in ("timer", "_settle_timer"):
                timer = getattr(self, attribute)
                if timer is not None:
                    self.after_cancel(timer)
                    setattr(self, attribute, None)
