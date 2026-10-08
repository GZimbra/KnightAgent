"""Compact, keyboard-accessible conversation list for the desktop sidebar."""

from time import monotonic
import tkinter as tk
from tkinter import font as tkfont

from knightagent.gui import theme
from knightagent.gui.theme import BLACK, WHITE, ORANGE, SIDEBAR, BORDER, MUTED


def _blend(start, end, amount):
    amount = max(0.0, min(1.0, amount))
    return "#" + "".join(
        f"{round(int(start[i:i + 2], 16) * (1 - amount) + int(end[i:i + 2], 16) * amount):02x}"
        for i in (1, 3, 5)
    )


class HistoryList(tk.Canvas):
    """Single-selection list with a small Listbox-compatible public API.

    Programmatic selection is silent; pointer and keyboard actions emit the
    standard ``<<ListboxSelect>>`` event. Only visible rows are painted.
    """

    row_height = 42
    inset = 4

    def __init__(self, parent, **kwargs):
        font = kwargs.pop("font", (theme.UI_FONT, 12))
        self._foreground = kwargs.pop("fg", kwargs.pop("foreground", WHITE))
        # Accept conventional Listbox appearance options during migration.
        for option in ("selectbackground", "selectforeground", "activestyle", "exportselection"):
            kwargs.pop(option, None)
        kwargs.setdefault("background", kwargs.pop("bg", SIDEBAR))
        kwargs.setdefault("width", 220)
        kwargs.setdefault("height", 240)
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("borderwidth", 0)
        kwargs.setdefault("takefocus", True)
        kwargs.setdefault("yscrollincrement", 1)
        super().__init__(parent, **kwargs)
        self.row_height = round(42*max(1.0, self.winfo_fpixels("1i")/96))
        self._font = tkfont.Font(root=self, font=font)
        self._titles = []
        self._selected = None
        self._hovered = None
        self._focused = False
        self._hover_levels = {}
        self._animation = None
        self._redraw_job = None
        self._last_frame = monotonic()
        self._wheel_remainder = 0.0
        self.bind("<Configure>", self._schedule_draw)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _event: self._set_hover(None))
        self.bind("<Button-1>", self._click)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda _event: self._scroll(-1))
        self.bind("<Button-5>", lambda _event: self._scroll(1))
        self.bind("<FocusIn>", lambda _event: self._focus(True))
        self.bind("<FocusOut>", lambda _event: self._focus(False))
        for key in ("Up", "Down", "Home", "End", "Return", "space"):
            self.bind(f"<{key}>", self._key)
        self.bind("<Destroy>", self._destroy)
        self._update_region()

    def configure(self, cnf=None, **kwargs):
        result = super().configure(cnf, **kwargs)
        if hasattr(self, "_titles") and (kwargs or isinstance(cnf, dict)):
            if self.cget("state") == "disabled":
                self._set_hover(None)
            self._schedule_draw()
        return result

    config = configure

    def insert(self, index, *titles):
        position = self._index(index, insertion=True)
        if not titles:
            return
        self._titles[position:position] = [str(title) for title in titles]
        if self._selected is not None and position <= self._selected:
            self._selected += len(titles)
        self._clear_hover()
        self._update_region()

    def delete(self, first, last=None):
        if not self._titles:
            return
        start = self._index(first)
        end = self._index(first if last is None else last)
        if start > end or start >= len(self._titles):
            return
        del self._titles[start:end + 1]
        if self._selected is not None:
            if start <= self._selected <= end:
                self._selected = None
            elif self._selected > end:
                self._selected -= end - start + 1
        self._clear_hover()
        self._update_region()

    def selection_set(self, first, last=None):
        if self._titles:
            index = self._index(first)
            if index < len(self._titles):
                self._selected = index
                self._schedule_draw()

    select_set = selection_set

    def selection_clear(self, first, last=None):
        start = self._index(first)
        end = self._index(first if last is None else last)
        if self._selected is not None and start <= self._selected <= end:
            self._selected = None
            self._schedule_draw()

    select_clear = selection_clear

    def curselection(self):
        return () if self._selected is None else (self._selected,)

    def size(self):
        return len(self._titles)

    def get(self, first, last=None):
        index = self._index(first)
        if last is not None:
            return tuple(self._titles[index:self._index(last) + 1])
        return self._titles[index] if index < len(self._titles) else ""

    def yview(self, *args):
        result = super().yview(*args)
        if args:
            self._clear_hover()
            self._schedule_draw()
        return result

    def yview_moveto(self, fraction):
        self.yview("moveto", fraction)

    def yview_scroll(self, number, what):
        self.yview("scroll", number, what)

    def see(self, index):
        if not self._titles:
            return
        index = self._index(index)
        top = self.canvasy(0)
        bottom = top + self.winfo_height()
        row_top = self.inset + index * self.row_height
        total = max(self.winfo_height(), len(self._titles) * self.row_height + self.inset * 2)
        if row_top < top:
            self.yview_moveto(max(0, row_top - self.inset) / total)
        elif row_top + self.row_height > bottom:
            self.yview_moveto((row_top + self.row_height + self.inset - self.winfo_height()) / total)

    def _index(self, value, insertion=False):
        if value == "end":
            return len(self._titles) if insertion else max(0, len(self._titles) - 1)
        return min(len(self._titles), max(0, int(value)))

    def _update_region(self):
        super().configure(scrollregion=(0, 0, max(1, self.winfo_width()),
                                       len(self._titles) * self.row_height + self.inset * 2))
        self._schedule_draw()

    def _schedule_draw(self, _event=None):
        if self._redraw_job is None:
            self._redraw_job = self.after_idle(self._draw)

    def _draw(self):
        self._redraw_job = None
        super().delete("history-row")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 4 or height < 2:
            return
        super().configure(scrollregion=(0, 0, width,
                                       len(self._titles) * self.row_height + self.inset * 2))
        first = max(0, int((self.canvasy(0) - self.inset) // self.row_height))
        last = min(len(self._titles), int((self.canvasy(height) - self.inset) // self.row_height) + 2)
        disabled = self.cget("state") == "disabled"
        background = self.cget("background")
        for index in range(first, last):
            y = self.inset + index * self.row_height
            selected = index == self._selected
            hover = self._hover_levels.get(index, 0.0) if not disabled else 0.0
            tone = .10 + .02 * hover if selected else .05 * hover
            fill = _blend(background, ORANGE if selected else WHITE, tone)
            outline = _blend(BORDER, ORANGE, .42 if self._focused else .18) if selected else fill
            self._rounded(2, y + 2, width - 2, y + self.row_height - 2,
                          fill=fill, outline=outline)
            if selected:
                self.create_line(4, y + 12, 4, y + self.row_height - 12,
                                 fill=ORANGE, width=2, capstyle="round", tags="history-row")
            center = y + self.row_height / 2
            text_color = MUTED if disabled else self._foreground if selected else _blend(MUTED, WHITE, .64)
            icon_color = _blend(BLACK, ORANGE, .62) if disabled and selected else ORANGE if selected else MUTED
            # A restrained conversation mark leaves the title the dominant item.
            self.create_line(17, center + 4, 14, center + 7, 14, center - 5,
                             26, center - 5, 26, center + 4, 17, center + 4,
                             fill=icon_color, width=1.15, joinstyle="round", tags="history-row")
            self.create_text(37, center, anchor="w", text=self._truncate(self._titles[index], width - 52),
                             font=self._font, fill=text_color, tags="history-row")

    def _rounded(self, left, top, right, bottom, **kwargs):
        radius = min(9, max(0, (right - left) / 2))
        points = (left + radius, top, right - radius, top, right, top,
                  right, top + radius, right, bottom - radius, right, bottom,
                  right - radius, bottom, left + radius, bottom, left, bottom,
                  left, bottom - radius, left, top + radius, left, top)
        self.create_polygon(points, smooth=True, splinesteps=16, width=1,
                            tags="history-row", **kwargs)

    def _truncate(self, title, available):
        title = " ".join(title.split())
        if available <= 0:
            return ""
        if self._font.measure(title) <= available:
            return title
        if self._font.measure("…") > available:
            return ""
        low, high = 0, len(title)
        while low < high:
            middle = (low + high + 1) // 2
            if self._font.measure(title[:middle] + "…") <= available:
                low = middle
            else:
                high = middle - 1
        return title[:low].rstrip() + "…"

    def _row_at(self, event):
        if self.cget("state") == "disabled" or event.x < 0 or event.x >= self.winfo_width():
            return None
        index = int((self.canvasy(event.y) - self.inset) // self.row_height)
        return index if 0 <= index < len(self._titles) else None

    def _motion(self, event):
        self._set_hover(self._row_at(event))

    def _set_hover(self, index):
        if index == self._hovered:
            return
        self._hovered = index
        super().configure(cursor="hand2" if index is not None else "")
        if index is not None:
            self._hover_levels.setdefault(index, 0.0)
        if self._animation is None:
            self._last_frame = monotonic()
            self._animation = self.after(16, self._animate)

    def _clear_hover(self):
        self._hovered = None
        self._hover_levels.clear()
        super().configure(cursor="")

    def _animate(self):
        self._animation = None
        now = monotonic()
        step = min(1.0, (now - self._last_frame) / .12)
        self._last_frame = now
        moving = False
        for index in tuple(self._hover_levels):
            target = 1.0 if index == self._hovered else 0.0
            current = self._hover_levels[index]
            value = min(target, current + step) if target > current else max(target, current - step)
            if value == 0:
                del self._hover_levels[index]
            else:
                self._hover_levels[index] = value
            moving = moving or value != target
        self._schedule_draw()
        if moving:
            self._animation = self.after(16, self._animate)

    def _click(self, event):
        index = self._row_at(event)
        if index is not None:
            self.focus_set()
            self._choose(index)
        return "break"

    def _choose(self, index, activate=False):
        changed = self._selected != index
        self._selected = index
        self.see(index)
        self._schedule_draw()
        if changed or activate:
            self.event_generate("<<ListboxSelect>>")

    def _key(self, event):
        if self.cget("state") == "disabled" or not self._titles:
            return "break"
        index = self._selected
        if event.keysym == "Home":
            index = 0
        elif event.keysym == "End":
            index = len(self._titles) - 1
        elif event.keysym == "Up":
            index = len(self._titles) - 1 if index is None else max(0, index - 1)
        elif event.keysym == "Down":
            index = 0 if index is None else min(len(self._titles) - 1, index + 1)
        elif index is None:
            index = 0
        self._choose(index, activate=event.keysym in ("Return", "space"))
        return "break"

    def _focus(self, focused):
        self._focused = focused
        self._schedule_draw()

    def _scroll(self, rows):
        self.yview_scroll(rows * self.row_height, "units")
        return "break"

    def _wheel(self, event):
        self._wheel_remainder -= event.delta / 120
        rows = int(self._wheel_remainder)
        if rows:
            self._wheel_remainder -= rows
            self._scroll(rows)
        return "break"

    def _destroy(self, event):
        if event.widget is not self:
            return
        for job in (self._animation, self._redraw_job):
            if job is not None:
                self.after_cancel(job)
        self._animation = self._redraw_job = None
