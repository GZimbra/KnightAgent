"""Interactive, paged Tk graph of the local knowledge and chat archive."""

from collections import Counter
import math
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
from tkinter import ttk

from knightagent.gui import theme
from knightagent.gui.buttons import RoundedButton
from knightagent.gui.graph_data import load_graph


COLORS = {
    "root": theme.ORANGE, "database": theme.WHITE, "workspace": "#6bc8e6",
    "chat": "#90b5ff", "message": "#a9a9a9", "tool": "#bb9cff",
    "family": "#77cdb9", "document": "#77cdb9", "chunk": "#777777",
    "example": theme.ORANGE, "file": "#cfb987",
    "sync": "#c2c2c2",
}
PAGE_SIZE = 60


class GraphPanel(ttk.Frame):
    def __init__(self, parent, directory, on_back):
        super().__init__(parent)
        self.directory = directory
        self.on_back = on_back
        self.graph = None
        self.focus = "root"
        self.page = 0
        self.zoom = 1.0
        self.drag = None
        self.hits = {}
        self.results = Queue()
        self.loading = False
        self.search_term = None
        self.search_index = -1
        self._build()
        self.refresh()

    def _build(self):
        header = ttk.Frame(self, padding=(24, 18, 24, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Mapa da memória", font=(theme.UI_FONT, 21, "bold")).pack(side="left")
        RoundedButton(header, text="Atualizar", command=self.refresh).pack(side="right")
        RoundedButton(header, text="Voltar à conversa", command=self.on_back).pack(side="right", padx=(0, 8))
        controls = ttk.Frame(self, padding=(24, 0, 24, 12))
        controls.pack(fill="x")
        self.query = tk.StringVar()
        search = ttk.Entry(controls, textvariable=self.query)
        search.pack(side="left", fill="x", expand=True)
        search.bind("<Return>", lambda _: self.search())
        RoundedButton(controls, text="Buscar", command=self.search).pack(side="left", padx=(8, 0))
        RoundedButton(controls, text="Início", command=lambda: self.select("root")).pack(side="left", padx=(8, 0))
        self.summary = tk.StringVar(value="Lendo as bases locais…")
        ttk.Label(self, textvariable=self.summary, style="Muted.TLabel", wraplength=900,
                  padding=(24, 0, 24, 10)).pack(fill="x")
        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        graph_frame = ttk.Frame(body)
        body.add(graph_frame, weight=4)
        self.canvas = tk.Canvas(graph_frame, bg="#101010", highlightthickness=1,
                                highlightbackground=theme.BORDER, cursor="hand2")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self.draw())
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<ButtonPress-2>", self._drag_start)
        self.canvas.bind("<B2-Motion>", self._drag_move)
        side = ttk.Frame(body, padding=(14, 0, 0, 0))
        body.add(side, weight=2)
        ttk.Label(side, text="DETALHES", style="Muted.TLabel",
                  font=(theme.UI_FONT, 10, "bold")).pack(anchor="w", pady=(2, 8))
        self.details = tk.Text(side, bg=theme.SURFACE, fg=theme.WHITE, wrap="word",
                               relief="flat", padx=15, pady=15, font=(theme.UI_FONT, 11),
                               insertbackground=theme.ORANGE)
        self.details.pack(fill="both", expand=True)
        self.details.configure(state="disabled")
        pager = ttk.Frame(self, padding=(24, 0, 24, 14))
        pager.pack(fill="x")
        self.previous = RoundedButton(pager, text="← Anterior", command=lambda: self._page(-1))
        self.previous.pack(side="left")
        self.page_label = ttk.Label(pager, text="", style="Muted.TLabel")
        self.page_label.pack(side="left", padx=14)
        self.next = RoundedButton(pager, text="Próxima →", command=lambda: self._page(1))
        self.next.pack(side="left")
        ttk.Label(pager, text="Clique para explorar · Roda: zoom · Botão central: mover",
                  style="Muted.TLabel").pack(side="right")

    def refresh(self):
        if self.loading:
            return
        self.loading = True
        self.summary.set("Atualizando o grafo das bases locais…")
        def worker():
            try:
                self.results.put(("ok", load_graph(self.directory)))
            except Exception as error:
                self.results.put(("error", str(error)))
        Thread(target=worker, daemon=True).start()
        self.after(80, self._poll)

    def _poll(self):
        try:
            kind, result = self.results.get_nowait()
        except Empty:
            self.after(80, self._poll)
            return
        self.loading = False
        if kind == "error":
            self.summary.set("Falha ao ler as bases locais: " + result)
            return
        self.graph = result
        if self.focus not in result.nodes:
            self.focus = "root"
        counts = Counter(node["kind"] for node in result.nodes.values())
        self.counts = counts
        self.select(self.focus)

    def search(self):
        if self.graph is None:
            return
        query = self.query.get().casefold().strip()
        if not query:
            self.select("root")
            return
        matches = [key for key, node in self.graph.nodes.items()
                   if query in node["label"].casefold() or query in node["detail"].casefold()]
        if not matches:
            self.summary.set(f"Nenhum registro encontrado para: {query}")
            return
        self.search_index = (self.search_index + 1) % len(matches) if query == self.search_term else 0
        self.search_term = query
        self.select(matches[self.search_index])
        self.summary.set(f"Busca: {self.search_index + 1}/{len(matches)} · pressione Buscar novamente para avançar.")

    def select(self, key):
        if self.graph is None or key not in self.graph.nodes:
            return
        self.focus = key
        self.page = 0
        self._draw_selection()

    def _page(self, direction):
        self.page = max(0, self.page + direction)
        self._draw_selection()

    def _draw_selection(self):
        node = self.graph.nodes[self.focus]
        neighbors = sorted(self.graph.neighbors[self.focus],
                           key=lambda key: (self.graph.nodes[key]["kind"], self.graph.nodes[key]["label"].casefold()))
        pages = max(1, math.ceil(len(neighbors) / PAGE_SIZE))
        self.page = min(self.page, pages - 1)
        self.page_label.configure(text=f"{self.page + 1}/{pages} · {len(neighbors)} conexões")
        self.previous.configure(state="normal" if self.page else "disabled")
        self.next.configure(state="normal" if self.page < pages - 1 else "disabled")
        text = (f"{node['label']}\n{node['kind']}"
                + (" · NOVO CONHECIMENTO REGISTRADO" if node.get("new") else "")
                + f"\n{len(neighbors)} conexões\n\n{node['detail']}")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")
        self.summary.set(
            f"{len(self.graph.nodes):,} registros · {len(self.graph.edges):,} relações · "
            f"{self.counts['chat']:,} chats · {self.counts['message']:,} mensagens · "
            f"{self.counts['document']:,} documentos · {self.counts['chunk']:,} trechos · "
            f"{self.counts['example']:,} exemplos aprovados · {self.counts['tool']:,} ferramentas. "
            "Laranja: exemplos aprovados e documentos importados. "
            "Referências recuperadas são vinculadas a novos pedidos; o histórico antigo não registra essas ligações. "
            "Não há cadastro de skills nesta versão; chamadas de ferramentas registradas aparecem no mapa."
        )
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        self.hits = {}
        if self.graph is None:
            return
        width, height = max(200, self.canvas.winfo_width()), max(200, self.canvas.winfo_height())
        cx, cy = width / 2, height / 2
        neighbors = sorted(self.graph.neighbors[self.focus],
                           key=lambda key: (self.graph.nodes[key]["kind"], self.graph.nodes[key]["label"].casefold()))
        visible = neighbors[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        radius = min(width * .40, height * .41) * self.zoom
        positions = {self.focus: (cx, cy)}
        for index, key in enumerate(visible):
            inner = index < 20
            ring_index = index if inner else index - 20
            ring_count = min(20, len(visible)) if inner else max(1, len(visible) - 20)
            angle = 2 * math.pi * ring_index / ring_count - math.pi / 2
            distance = radius * (.55 if inner and len(visible) > 20 else 1)
            positions[key] = (cx + distance * math.cos(angle), cy + distance * math.sin(angle))
        for a, b in self.graph.edges:
            if a in positions and b in positions:
                x1, y1 = positions[a]
                x2, y2 = positions[b]
                self.canvas.create_line(x1, y1, x2, y2, fill="#464646", width=1)
        for key, (x, y) in positions.items():
            node = self.graph.nodes[key]
            focus = key == self.focus
            r = 13 if focus else (6 if len(visible) > 35 else 8)
            color = theme.ORANGE if node.get("new") else COLORS.get(node["kind"], theme.WHITE)
            item = self.canvas.create_oval(x-r, y-r, x+r, y+r, fill=color,
                                           outline=theme.WHITE if focus else "", width=2 if focus else 0)
            self.hits[item] = key
            if focus or len(visible) <= 28:
                label = node["label"][:25] + ("…" if len(node["label"]) > 25 else "")
                text = self.canvas.create_text(x, y-r-8, text=label, fill=theme.WHITE,
                                               anchor="s", font=(theme.UI_FONT, 10, "bold" if focus else "normal"))
                self.hits[text] = key

    def _click(self, event):
        for item in reversed(self.canvas.find_overlapping(event.x-5, event.y-5, event.x+5, event.y+5)):
            if item in self.hits:
                self.select(self.hits[item])
                return

    def _wheel(self, event):
        self.zoom = max(.35, min(2.0, self.zoom * (1.1 if event.delta > 0 else .9)))
        self.draw()

    def _drag_start(self, event):
        self.drag = (event.x, event.y)

    def _drag_move(self, event):
        if self.drag is not None:
            self.canvas.move("all", event.x - self.drag[0], event.y - self.drag[1])
            self.drag = (event.x, event.y)
