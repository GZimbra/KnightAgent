"""Responsive Tk chat cards and observable execution flow."""

import math
from time import monotonic
import tkinter as tk
from tkinter import ttk

from . import theme
from .buttons import rounded_png
from .branding import APP_NAME
from .theme import BLACK, WHITE, ORANGE, SURFACE, USER_SURFACE, BORDER, MUTED, blend


class RoundedPanel(tk.Frame):
    def __init__(self, parent, variant="surface"):
        super().__init__(parent, bg=BLACK)
        self.surface = {"user": USER_SURFACE, "flow": theme.FLOW_SURFACE}.get(variant, SURFACE)
        self.highlight = {"user": "#352214", "flow": "#20160f"}.get(variant, "#2c1c11")
        self.rim_color = "#241a13" if variant == "flow" else BORDER
        self.radius = 16 if variant == "flow" else 22
        self.gradient_height = 9 if variant == "flow" else 14
        self.border_level = 0.0
        self.selected = False
        self.hovered = False
        self.effect_timer = None
        self._panel_size = None
        self._rim_rgb = None
        self._cap_source = tk.PhotoImage(master=self)
        self._top_cap = tk.PhotoImage(master=self)
        self._bottom_cap = tk.PhotoImage(master=self)
        self.canvas = canvas = tk.Canvas(self, bg=BLACK, highlightthickness=0)
        canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = ttk.Frame(self, padding=(0, 0), style={"user": "User.TFrame", "flow": "Flow.TFrame"}.get(variant, "Surface.TFrame"))
        self.body.pack(fill="both", expand=True, padx=16, pady=9 if variant == "flow" else 14)
        self.body.lift()
        canvas.bind("<Configure>", lambda event: self._outline(canvas, event.width, event.height))
        self.bind("<Destroy>", self._destroy_effect)

    def bind_effects(self, on_select=None):
        def visit(widget):
            widget.bind("<Enter>", lambda _: self._hover(True), add="+")
            widget.bind("<Leave>", self._leave, add="+")
            if on_select is not None:
                widget.bind("<Button-1>", lambda _: on_select(), add="+")
            for child in widget.winfo_children():
                visit(child)
        visit(self)

    def _leave(self, event):
        x, y = event.x_root, event.y_root
        if not (self.winfo_rootx() <= x < self.winfo_rootx()+self.winfo_width()
                and self.winfo_rooty() <= y < self.winfo_rooty()+self.winfo_height()):
            self._hover(False)

    def _hover(self, value):
        self.hovered = value
        self._start_effect()

    def set_selected(self, selected):
        self.selected = selected
        self._start_effect()

    def _start_effect(self):
        if self.effect_timer is None:
            self._effect()

    def _effect(self):
        self.effect_timer = None
        target = .42 if self.selected else .18 if self.hovered else 0.0
        self.border_level += (target-self.border_level)*.3
        if abs(target-self.border_level) < .015:
            self.border_level = target
        self._paint_rim()
        if self.border_level != target:
            self.effect_timer = self.after(16, self._effect)

    def _destroy_effect(self, event):
        if event.widget is self and self.effect_timer is not None:
            self.after_cancel(self.effect_timer)
            self.effect_timer = None

    def _outline(self, canvas, width, height):
        if width < 2 or height < 2 or self._panel_size == (width, height):
            return
        self._panel_size = width, height
        self._rim_rgb = None
        canvas.delete("outline")
        self._cap_height = min(self.radius, height // 2)
        cap = self._cap_height
        # Render the rounded ends at their allocated size. The large flat body
        # needs no bitmap; only these small strips change during a rim fade.
        canvas.create_rectangle(0, cap, width, height-cap, fill=self.surface,
                                width=0, tags="outline")
        canvas.create_image(0, 0, image=self._top_cap, anchor="nw", tags="outline")
        canvas.create_image(0, height-cap, image=self._bottom_cap, anchor="nw", tags="outline")
        canvas.create_rectangle(0, cap, 1, height-cap, fill=self.rim_color,
                                width=0, tags=("outline", "rim"))
        canvas.create_rectangle(width-1, cap, width, height-cap, fill=self.rim_color,
                                width=0, tags=("outline", "rim"))
        self._paint_rim()

    def _paint_rim(self):
        if self._panel_size is None:
            return
        border = blend(self.rim_color, ORANGE, self.border_level)
        if border == self._rim_rgb:
            return
        self._rim_rgb = border
        width, _height = self._panel_size
        cap = self._cap_height
        def rgb(color):
            return tuple(int(color[index:index+2], 16) for index in (1, 3, 5))
        png = rounded_png(width, cap*2, cap, 1, rgb(self.highlight), rgb(self.surface),
                          rgb(border), rgb(BLACK), gradient_height=self.gradient_height)
        self._cap_source.configure(width=width, height=cap*2, data=png, format="png")
        for target, offset in ((self._top_cap, 0), (self._bottom_cap, cap)):
            target.configure(width=width, height=cap)
            self.tk.call(str(target), "copy", str(self._cap_source), "-from",
                         0, offset, width, offset+cap, "-to", 0, 0)
        self.canvas.itemconfigure("rim", fill=border)


class ScrollArea(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BLACK, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self._resize)
        self.body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.body.bind("<MouseWheel>", self._wheel)

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)

    def _wheel(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def follow(self):
        self.update_idletasks()
        self.canvas.yview_moveto(1)

    def clear(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.canvas.yview_moveto(0)

    def bind_wheel(self, widget):
        if not isinstance(widget, tk.Text):
            widget.bind("<MouseWheel>", self._wheel)
        for child in widget.winfo_children():
            self.bind_wheel(child)


class ReadableText(tk.Text):
    """Selectable, copyable text; long output scrolls within its card."""

    def __init__(self, parent, text, accent=False, code=False, surface=BLACK, muted=False):
        super().__init__(parent, wrap="word", height=1, width=1,
                         bg=surface, fg=ORANGE if accent else MUTED if muted else WHITE,
                         font=("Consolas" if code else theme.UI_FONT, 12 if code else 13),
                         relief="flat", borderwidth=0, highlightthickness=0,
                         selectbackground=ORANGE, selectforeground=BLACK,
                         padx=0, pady=4, cursor="xterm", spacing1=2, spacing3=4)
        self.insert("1.0", text)
        self.configure(state="disabled")
        self.bind("<Configure>", self._resize)
        self.bind("<Control-a>", self._select_all)
        self.bind("<MouseWheel>", self._wheel)

    def _wheel(self, event):
        if int(self.cget("height")) >= 18:
            return None
        parent = self.master
        while parent is not None:
            if isinstance(parent, ScrollArea):
                return parent._wheel(event)
            parent = parent.master

    def _select_all(self, _):
        self.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _resize(self, _):
        lines = self.count("1.0", "end", "displaylines")
        height = max(1, min(18, (lines or (1,))[0]))
        if int(self.cget("height")) != height:
            self.configure(height=height)


def event_title(kind, content):
    if kind == "result":
        return "Resposta"
    if kind == "error":
        return "Execução interrompida"
    if kind == "diff":
        return "Alteração proposta"
    if kind == "approval":
        return "Aprovação solicitada"
    if kind == "decision":
        return "Sua decisão"
    if content.startswith("Planejando"):
        return "Análise do pedido"
    if content.startswith("Plano preparado"):
        return "Plano preparado"
    if content.startswith("Executando"):
        return "Execução"
    if content.startswith("Revisando") or content.startswith("APROVADO"):
        return "Revisão"
    if content.startswith("["):
        return "Ferramenta / resultado"
    if content.startswith("AVISO"):
        return "Aviso"
    return "Registro da execução"


class FlowCard(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=(0, 12, 0, 14))
        self.pack(fill="x", padx=8, pady=(0, 16))
        ttk.Label(self, text=APP_NAME, font=(theme.UI_FONT, 13, "bold")).pack(anchor="w", pady=(0, 14))
        self.nodes = []
        self.graph = ttk.Frame(self)
        self.graph.pack(fill="x")
        self.rail = tk.Canvas(self.graph, width=28, height=1, bg=BLACK, highlightthickness=0)
        self.rail.pack(side="left", fill="y")
        self.steps = ttk.Frame(self.graph)
        self.steps.pack(side="left", fill="both", expand=True)
        self.links = []
        self.markers = []
        self.timer = None
        self.running = False
        self.selected_node = None
        self.rail.bind("<Configure>", lambda _: self._draw_links())
        self.steps.bind("<Configure>", lambda _: self._draw_links())
        self.bind("<Destroy>", self._destroy_motion)

    def set_running(self, running):
        self.running = running
        self._ensure_motion()

    def select_node(self, selected):
        self.selected_node = selected
        for _, _, node in self.nodes:
            node.panel.set_selected(node is selected)

    def _ensure_motion(self):
        if self.timer is None and (self.running or any(link["progress"] < 1 for link in self.links)):
            self.timer = self.after(16, self._tick_motion)
        elif not self.running:
            self._draw_links()

    def _tick_motion(self):
        self.timer = None
        self._draw_links()
        self._ensure_motion()

    def _draw_links(self):
        now = monotonic()
        for index, (_, _, node) in enumerate(self.nodes):
            cy = node.winfo_y() + 22
            radius = 4.5
            color = ORANGE
            if self.running and index == len(self.nodes)-1:
                radius += 1.5*(.5+.5*math.sin(now*4))
                color = blend(ORANGE, WHITE, .25*(.5+.5*math.sin(now*4)))
            self.rail.coords(self.markers[index], 13-radius, cy-radius, 13+radius, cy+radius)
            self.rail.itemconfigure(self.markers[index], fill=color)
        for index, link in enumerate(self.links):
            progress = min(1.0, max(0.0, (now-link["start"])/.48)) if link["progress"] < 1 else 1.0
            link["progress"] = progress
            start = self.nodes[index][2].winfo_y()+30
            end = self.nodes[index+1][2].winfo_y()+14
            eased = 1-(1-progress)**3
            tip = start+max(0, end-start)*eased
            self.rail.coords(link["line"], 13, start, 13, tip)
            self.rail.itemconfigure(link["line"], state="normal" if progress > 0 else "hidden",
                                    fill=ORANGE if progress < 1 else BORDER)
            self.rail.coords(link["spark"], 10, tip-3, 16, tip+3)
            self.rail.itemconfigure(link["spark"], state="normal" if 0 < progress < 1 else "hidden")

    def _destroy_motion(self, event):
        if event.widget is self and self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None

    def add(self, kind, content, animate=True):
        if kind == "result":
            for old_kind, old_content, node in self.nodes:
                if old_kind == "event" and old_content == content:
                    node.heading.configure(text="Resposta")
                    node.text.configure(fg=WHITE, font=(theme.UI_FONT, 13))
                    return
        node = ttk.Frame(self.steps)
        node.pack(fill="x", pady=(0, 8))
        node.panel = panel = RoundedPanel(node, variant="flow")
        panel.pack(side="left", fill="both", expand=True)
        content_frame = panel.body
        node.heading = ttk.Label(content_frame, text=event_title(kind, content),
                                 font=(theme.UI_FONT, 12, "bold"), foreground=WHITE, style="Flow.TLabel")
        node.heading.pack(anchor="w")
        text_frame = ttk.Frame(content_frame, style="Flow.TFrame")
        text_frame.pack(fill="x")
        text = ReadableText(text_frame, content, code=kind == "diff", surface=panel.surface, muted=kind not in {"result", "error"})
        text.pack(side="left", fill="x", expand=True)
        node.text = text
        if content in {"Planejando...", "Executando...", "Revisando...", "Plano preparado."}:
            text_frame.pack_forget()
        scrollbar = ttk.Scrollbar(text_frame, command=text.yview)
        def scroll_state(first, last):
            scrollbar.set(first, last)
            if float(first) > 0 or float(last) < .999:
                scrollbar.pack(side="right", fill="y")
            else:
                scrollbar.pack_forget()
        text.configure(yscrollcommand=scroll_state)
        self.nodes.append((kind, content, node))
        self.markers.append(self.rail.create_oval(0, 0, 0, 0, fill=ORANGE, outline=""))
        if len(self.nodes) > 1:
            start = monotonic()
            if animate and self.links:
                start = max(start, self.links[-1]["start"]+.48)
            self.links.append({"line": self.rail.create_line(0, 0, 0, 0, fill=ORANGE,
                                                              width=2, arrow="last", arrowshape=(7, 9, 4)),
                               "spark": self.rail.create_oval(0, 0, 0, 0, fill=WHITE, outline=""),
                               "start": start, "progress": 0.0 if animate else 1.0})
        panel.bind_effects(lambda: self.select_node(node))
        self._draw_links()
        self._ensure_motion()


def user_card(parent, content):
    card = RoundedPanel(parent, variant="user")
    card.pack(fill="x", padx=(80, 8), pady=(18, 12))
    text = ReadableText(card.body, content, surface=USER_SURFACE)
    text.pack(side="left", fill="x", expand=True)
    scrollbar = ttk.Scrollbar(card.body, command=text.yview)
    def scroll_state(first, last):
        scrollbar.set(first, last)
        if float(first) > 0 or float(last) < .999:
            scrollbar.pack(side="right", fill="y")
        else:
            scrollbar.pack_forget()
    text.configure(yscrollcommand=scroll_state)
    card.bind_effects()
