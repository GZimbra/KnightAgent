"""Native chat with persistent conversations and observable execution flows."""

from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from knightagent.gui.buttons import RoundedButton
from knightagent.gui.branding import APP_NAME, apply_app_icon, sidebar_logo
from knightagent.gui.window_chrome import apply_window_chrome, configure_app_identity

from knightagent.agent.loop import Agent
from knightagent.agent.memory import MemoryStore
from knightagent.knowledge import KnowledgeBase
from knightagent.config.settings import build_providers, load
from knightagent.gui.settings import SettingsPanel
from knightagent.gui import theme
from knightagent.gui.theme import BLACK, WHITE, ORANGE, SIDEBAR, SURFACE, BORDER, ThinkingOrb, apply_theme
from knightagent.gui.history import ChatHistory
from knightagent.gui.history_list import HistoryList
from knightagent.gui.chat_widgets import ScrollArea, FlowCard, RoundedPanel, user_card
from knightagent.tools.files import FileTools, Workspace, WriteApproval
from knightagent.runtime import OllamaRuntime
from knightagent.copilot_client import CopilotClient


class DesktopApp:
    def __init__(self, root, config_path="config.yaml"):
        self.root = root
        self.config_path = Path(config_path).resolve()
        self.config = load(self.config_path)
        self.events = Queue()
        self.busy = False
        self.closing = False
        self.starting = False
        self.runtime_ready = False
        self.runtime = OllamaRuntime(self.config, self.config_path)
        self.copilot_client = CopilotClient(self.config_path, self.config["complementary"])
        self.runtime_thread = None
        self.approval = None
        self.providers = {}
        self.agent = None
        self.chat_id = None
        self.flow = None
        self.restored_dialog = []
        self.history = ChatHistory(self.config_path.parent / "knightagent-chats.sqlite3")
        self.workspace = tk.StringVar(value=self.config["workspace"])
        self._build()
        self._refresh_history()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.drain_timer = self.root.after(80, self._drain)
        self.start_timer = self.root.after(0, self._start_runtime)

    def _build(self):
        scale = max(1.0, self.root.winfo_fpixels("1i") / 96)
        px = lambda value: round(value * scale)
        self.root.title(APP_NAME)
        width = min(px(1240), self.root.winfo_screenwidth()-px(60))
        height = min(px(860), self.root.winfo_screenheight()-px(80))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(px(900), px(680))
        apply_theme(self.root)
        apply_app_icon(self.root, default=True)
        apply_window_chrome(self.root)
        shell = ttk.Frame(self.root)
        shell.pack(fill="both", expand=True)
        sidebar = ttk.Frame(shell, width=px(266), padding=(px(16), px(22)), style="Sidebar.TFrame")
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self.logo_image = sidebar_logo(self.root, scale)
        self.logo_label = ttk.Label(sidebar, image=self.logo_image, text=APP_NAME,
                                    style="Sidebar.TLabel", anchor="center")
        self.logo_label.pack(fill="x", pady=(0, px(24)))
        self.new_button = RoundedButton(sidebar, text="＋  Nova conversa", style="Ghost.TButton", command=self._new_chat)
        self.new_button.pack(fill="x")
        ttk.Label(sidebar, text="Conversas", style="SidebarMuted.TLabel").pack(anchor="w", padx=8, pady=(28, 10))
        history_frame = ttk.Frame(sidebar, style="Sidebar.TFrame")
        history_frame.pack(fill="both", expand=True)
        self.chat_list = HistoryList(history_frame)
        self.chat_list.pack(side="left", fill="both", expand=True)
        history_scroll = ttk.Scrollbar(history_frame, command=self.chat_list.yview)
        def history_scroll_state(first, last):
            history_scroll.set(first, last)
            if float(first) > 0 or float(last) < .999:
                history_scroll.pack(side="right", fill="y")
            else:
                history_scroll.pack_forget()
        self.chat_list.configure(yscrollcommand=history_scroll_state)
        self.chat_list.bind("<<ListboxSelect>>", self._open_chat)
        RoundedButton(sidebar, text="Configurações", style="Ghost.TButton", command=self._show_settings).pack(fill="x", pady=(18, 0))
        main = ttk.Frame(shell)
        main.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(main, padding=(px(28), px(16)))
        top.pack(fill="x")
        top.columnconfigure(0, weight=1)
        self.chat_title = tk.StringVar(value="Nova conversa")
        title = ttk.Label(top, textvariable=self.chat_title, font=(theme.UI_FONT, 13, "bold"), wraplength=px(400))
        title.grid(row=0, column=0, sticky="w")
        self.browse = RoundedButton(top, text="Pasta do projeto", command=self._select_folder)
        self.browse.grid(row=0, column=1, sticky="e", padx=(16, 0))
        self.folder_caption = tk.StringVar()
        def folder_caption(*_):
            self.folder_caption.set(Path(self.workspace.get()).name or self.workspace.get())
        self.workspace.trace_add("write", folder_caption)
        folder_caption()
        ttk.Label(top, textvariable=self.folder_caption, style="Muted.TLabel", font=(theme.UI_FONT, 11)).grid(row=1, column=0, sticky="w", pady=(6, 0))
        # One shared content column keeps messages, orb and composer aligned.
        stage = ttk.Frame(main)
        stage.pack(fill="both", expand=True)
        column = ttk.Frame(stage)
        column.place(relx=.5, y=0, anchor="n", relheight=1, width=px(760))
        stage.bind("<Configure>", lambda e: column.place_configure(width=max(1, min(px(800), e.width-px(56)))))
        hero = ttk.Frame(column, padding=(0, 4, 0, 12))
        hero.pack(fill="x")
        self.orb = ThinkingOrb(hero, size=px(116))
        self.orb.pack()
        self.status = tk.StringVar(value="O que vamos desenvolver?")
        status_label = ttk.Label(hero, textvariable=self.status, font=(theme.UI_FONT, 16),
                                 wraplength=px(650), justify="center", anchor="center")
        status_label.pack(fill="x", pady=(0, 4))
        hero.bind("<Configure>", lambda event: status_label.configure(wraplength=max(120, event.width - 16)))
        composer_shell = ttk.Frame(column, padding=(4, 12, 4, 14))
        composer_shell.pack(side="bottom", fill="x")
        border = RoundedPanel(composer_shell)
        border.pack(fill="x")
        self.composer_panel = border
        composer = border.body
        self.input = tk.Text(composer, height=2, width=1, wrap="word", bg=SURFACE, fg=WHITE,
                             insertbackground=ORANGE, selectbackground=ORANGE, selectforeground=BLACK,
                             relief="flat", borderwidth=0, highlightthickness=0, font=(theme.UI_FONT, 13), undo=True)
        self.input.pack(fill="x", pady=(2, 12))
        placeholder = tk.Label(self.input, text="Peça uma alteração ou faça uma pergunta...",
                               bg=SURFACE, fg=theme.MUTED, font=(theme.UI_FONT, 13), anchor="w", cursor="xterm")
        placeholder.place(x=2, y=1)
        placeholder.bind("<Button-1>", lambda _: self.input.focus_set())
        def update_placeholder(_event=None):
            if self.input.get("1.0", "end-1c"):
                placeholder.place_forget()
            else:
                placeholder.place(x=2, y=1)
            self.input.edit_modified(False)
        self.input.bind("<<Modified>>", update_placeholder)
        self.input.bind("<Return>", self._enter)
        self.input.bind("<FocusIn>", lambda _: border.set_selected(True))
        self.input.bind("<FocusOut>", lambda _: border.set_selected(False))
        actions = ttk.Frame(composer, style="Surface.TFrame")
        actions.pack(fill="x")
        self.model_label = ttk.Label(actions, text=self.config["ollama"]["model"],
                                     style="Surface.TLabel", foreground=theme.MUTED, font=(theme.UI_FONT, 11))
        self.model_label.pack(side="left")
        self.send_button = RoundedButton(actions, text="Enviar ↑", style="Accent.TButton", command=self._send)
        self.send_button.pack(side="right")
        self.copilot_button = RoundedButton(actions, text="Conta Copilot", command=self._show_copilot)
        self._update_copilot_button()
        border.bind_effects()
        ttk.Label(composer_shell, text="Enter para enviar  ·  Shift+Enter para nova linha", style="Muted.TLabel",
                  font=(theme.UI_FONT, 11)).pack(pady=(9, 0))
        self.approval_bar = ttk.Frame(column, padding=(8, 10))
        ttk.Label(self.approval_bar, text="Autorizar a alteração proposta?", style="Status.TLabel").pack(anchor="w", pady=(0, 8))
        for label, answer in (("Recusar", "n"), ("Aprovar", "s"), ("Aprovar tudo nesta sessão", "t")):
            RoundedButton(self.approval_bar, text=label, command=lambda a=answer: self._answer_approval(a)).pack(side="left", padx=(0, 8))
        self.feed = ScrollArea(column)
        self.feed.pack(fill="both", expand=True)
        self.empty = ttk.Label(self.feed.body, text="Peça uma alteração, explore seu projeto\nou comece uma ideia do zero.",
                               style="Muted.TLabel", justify="center", anchor="center", padding=24)
        self.empty.pack(fill="x", pady=10)
        self.settings_window = None
        self.input.focus_set()

    def _refresh_history(self):
        self.chats = self.history.list()
        self.chat_list.delete(0, "end")
        for index, chat in enumerate(self.chats):
            self.chat_list.insert("end", chat["title"])
            if chat["id"] == self.chat_id:
                self.chat_list.selection_set(index)

    def _reset_agent(self):
        if self.agent is not None and self.agent.knowledge is not None:
            self.agent.knowledge.close()
        for provider in self.providers.values():
            provider.close()
        self.providers = {}
        self.agent = None

    def _new_chat(self):
        if self.busy:
            return
        self._reset_agent()
        self.chat_id = None
        self.flow = None
        self.restored_dialog = []
        self.feed.clear()
        self.chat_title.set("Nova conversa")
        self.status.set("O que vamos desenvolver?")
        self.input.delete("1.0", "end")
        self.chat_list.selection_clear(0, "end")
        self.input.focus_set()

    def _open_chat(self, _event=None):
        selected = self.chat_list.curselection()
        if self.busy or not selected:
            return
        chat = self.chats[selected[0]]
        if self.chat_id == chat["id"]:
            return
        self._reset_agent()
        self.chat_id = chat["id"]
        self.workspace.set(chat["workspace"])
        self.chat_title.set(chat["title"])
        self.restored_dialog = self.history.dialog(self.chat_id)
        self.feed.clear()
        self.flow = None
        self.input.delete("1.0", "end")
        messages = self.history.messages(self.chat_id)
        for message in messages:
            self._render(message["kind"], message["content"])
        if messages and messages[-1]["kind"] not in {"end", "result", "error"}:
            self._render("error", "Esta execução foi interrompida. Nenhuma aprovação pendente foi retomada; envie um novo pedido para continuar.")
        self.status.set("Continue de onde parou")
        self.feed.follow()

    def _render(self, kind, content, animate=False):
        if hasattr(self, "empty") and self.empty.winfo_exists():
            self.empty.destroy()
        if kind == "user":
            user_card(self.feed.body, content)
            self.flow = FlowCard(self.feed.body)
        elif kind != "end":
            if self.flow is None:
                self.flow = FlowCard(self.feed.body)
            self.flow.add(kind, content, animate=animate)
        self.feed.bind_wheel(self.feed.body)

    def _record(self, kind, content):
        # Persist before display so reopening a chat preserves exactly its events.
        follow = kind == "user" or self.feed.canvas.yview()[1] >= .98
        try:
            self.history.append(self.chat_id, kind, content)
        except sqlite3.Error as error:
            self.status.set("Não foi possível salvar o histórico")
            messagebox.showerror("Histórico local", str(error), parent=self.root)
        self._render(kind, content, animate=True)
        if follow:
            self.feed.follow()

    def _show_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        window = self.settings_window = tk.Toplevel(self.root)
        window.title(f"{APP_NAME} · Configurações")
        apply_app_icon(window)
        apply_window_chrome(window)
        scale = max(1.0, self.root.winfo_fpixels("1i")/96)
        width = min(round(1060*scale), self.root.winfo_screenwidth()-round(70*scale))
        height = min(round(820*scale), self.root.winfo_screenheight()-round(90*scale))
        window.geometry(f"{width}x{height}")
        window.minsize(round(850*scale), round(640*scale))
        window.configure(bg=BLACK)
        self.settings_panel = SettingsPanel(window, self.config, self.config_path,
                                            on_save=self._settings_saved, is_busy=lambda: self.busy or self.starting,
                                            on_clear_history=self._clear_history,
                                            on_reset_memory=self._reset_memory)
        self.settings_panel.pack(fill="both", expand=True)

    def _clear_history(self):
        if self.busy or not messagebox.askyesno("Limpar histórico", "Excluir todas as conversas salvas neste computador?", parent=self.settings_window):
            return
        try:
            self.history.clear()
            self._new_chat()
            self._refresh_history()
        except sqlite3.Error as error:
            messagebox.showerror("Histórico", str(error), parent=self.root)

    def _reset_memory(self):
        if self.busy or not messagebox.askyesno("Resetar memória", "Excluir os exemplos de código aprovados da memória local? As conversas serão preservadas.", parent=self.settings_window):
            return
        try:
            MemoryStore(self.config_path.parent / "knightagent-memory.sqlite3", self.config["memory"]["scope"]).clear()
            self._reset_agent()
            self.restored_dialog = self.history.dialog(self.chat_id) if self.chat_id else []
        except (OSError, ValueError, sqlite3.Error) as error:
            messagebox.showerror("Memória local", str(error), parent=self.root)

    def _settings_saved(self, config, path):
        changed_model = config["ollama"] != self.config["ollama"]
        self._reset_agent()
        self.config = config
        self.config_path = Path(path)
        self.copilot_client.close()
        self.copilot_client = CopilotClient(self.config_path, config["complementary"])
        self.restored_dialog = self.history.dialog(self.chat_id) if self.chat_id else []
        self.model_label.configure(text=config["ollama"]["model"])
        self._update_copilot_button()
        if changed_model or not self.runtime_ready:
            self._start_runtime()
        else:
            self.status.set("Configurações atualizadas · IA local pronta")

    def _start_runtime(self):
        if self.starting or self.busy or self.closing:
            return
        self.starting = True
        self.runtime_ready = False
        self._visual_state("Iniciando IA local…", active=True)
        def start():
            try:
                self.runtime.close()
                if self.closing:
                    return
                self.runtime = OllamaRuntime(self.config, self.config_path)
                if self.closing:
                    self.runtime.close()
                    return
                self.runtime.start()
                if self.closing:
                    self.runtime.close()
                    return
                self.events.put(("runtime_status", "Carregando modelo local…"))
                self.runtime.preload()
                self.events.put(("runtime_ready", "IA local pronta · sem serviços de nuvem"))
            except Exception as error:
                self.events.put(("runtime_error", str(error)))
        self.runtime_thread = Thread(target=start, daemon=True)
        self.runtime_thread.start()

    def _update_copilot_button(self):
        if self.config.get("complementary", {}).get("copilot", False):
            self.copilot_button.pack(side="right", padx=(0, 10))
        else:
            self.copilot_button.pack_forget()

    def _show_copilot(self):
        if self.busy or self.starting or not self.config.get("complementary", {}).get("copilot", False):
            return
        self._show_settings()
        self.settings_panel.show_section("complementary")

    def _select_folder(self):
        if self.busy:
            return
        initial = self.workspace.get() if Path(self.workspace.get()).is_dir() else str(self.config_path.parent)
        selected = filedialog.askdirectory(parent=self.root, initialdir=initial)
        if selected and selected != self.workspace.get():
            self._new_chat()
            self.workspace.set(selected)

    def _visual_state(self, text, active=False):
        self.status.set(text)
        self.orb.set_active(active)
        if self.flow is not None:
            self.flow.set_running(active)
        state = "disabled" if self.busy or self.starting else "normal"
        for widget in (self.send_button, self.browse, self.new_button, self.input, self.chat_list):
            widget.configure(state=state)

    def _enter(self, event):
        if event.state & 0x0001:
            return None
        self._send()
        return "break"

    def _send(self):
        if self.busy or self.starting:
            return
        if not self.runtime_ready:
            self._start_runtime()
            return
        request = self.input.get("1.0", "end-1c").strip()
        if not request:
            return
        try:
            workspace = Workspace(self.workspace.get())
            if self.chat_id is None:
                title = " ".join(request.split())[:70]
                self.chat_id = self.history.create(workspace.root, title)
                self.chat_title.set(title)
        except (OSError, ValueError, sqlite3.Error) as error:
            messagebox.showerror("Não foi possível enviar", str(error), parent=self.root)
            return
        self._record("user", request)
        self._refresh_history()
        self.input.delete("1.0", "end")
        self.busy = True
        self._visual_state("Analisando seu pedido", active=True)
        Thread(target=self._run, args=(request, workspace), daemon=True).start()

    def _run(self, request, workspace):
        try:
            if self.agent is None or self.agent.tools.workspace.root != workspace.root:
                self._reset_agent()
                self.providers, roles = build_providers(self.config)
                approval = WriteApproval(ask=self._ask_approval, emit=lambda diff: self.events.put(("diff", diff)))
                tools = FileTools(workspace, approval, self.config["tool_output_chars"])
                memory = (MemoryStore(self.config_path.parent / "knightagent-memory.sqlite3", self.config["memory"]["scope"])
                          if self.config["memory"]["enabled"] else None)
                self.agent = Agent(self.providers, roles, tools, self.config,
                                   emit=self._emit_from_worker, memory=memory,
                                   complementary=self.copilot_client,
                                   knowledge=KnowledgeBase(self.config_path.parent / "knightagent-knowledge.sqlite3")
                                   if self.config["knowledge"]["enabled"] else None)
                self.agent.dialog = list(self.restored_dialog)
            result = self.agent.run(request)
            self.events.put(("result", result))
        except Exception as error:
            self.events.put(("error", str(error)))
        finally:
            self.events.put(("done", None))

    def _ask_approval(self, question):
        gate, answer = Event(), {}
        self.events.put(("approval", (question, gate, answer)))
        gate.wait()
        return answer.get("value", "n")

    def _answer_approval(self, answer="n"):
        if self.approval is None or answer not in {"s", "n", "t"}:
            return
        gate, result = self.approval
        self.approval = None
        self.approval_bar.pack_forget()
        labels = {"s": "Alteração aprovada.", "n": "Alteração recusada.", "t": "Alterações aprovadas para esta sessão de execução."}
        try:
            self._record("decision", labels[answer])
        finally:
            result["value"] = answer
            gate.set()
            self._visual_state("Executando", active=True)

    def _emit_from_worker(self, line):
        if line.startswith("AVISO: antes da primeira chamada"):
            gate = Event()
            self.events.put(("notice", (line, gate)))
            gate.wait()
        else:
            self.events.put(("event", line))

    def _drain(self):
        try:
            # Bound each batch so heavy output cannot starve animation/input.
            for _ in range(20):
                kind, value = self.events.get_nowait()
                if kind == "runtime_status":
                    self.status.set(value)
                elif kind in {"runtime_ready", "runtime_error"}:
                    self.starting = False
                    self.runtime_ready = kind == "runtime_ready"
                    self._visual_state(value)
                    if self.settings_window is not None and self.settings_window.winfo_exists():
                        self.settings_panel.refresh_models()
                elif kind in {"event", "diff", "error"}:
                    self._record(kind, value)
                    if value in {"Planejando...", "Executando...", "Revisando..."}:
                        self.status.set(value)
                elif kind == "result":
                    if value:
                        self._record("result", value)
                    else:
                        self._record("event", "Execução encerrada sem conclusão aprovada. Consulte as etapas acima.")
                elif kind == "approval":
                    question, gate, answer = value
                    self.approval = (gate, answer)
                    self._record("approval", question)
                    self._visual_state("Aguardando sua aprovação")
                    self.approval_bar.pack(fill="x", before=self.feed)
                elif kind == "notice":
                    line, gate = value
                    try:
                        self._record("event", line)
                        self.root.update_idletasks()
                    finally:
                        gate.set()
                elif kind == "done":
                    self.busy = False
                    self._record("end", "Execução encerrada")
                    self._visual_state("Pronto para o próximo pedido")
                    self._refresh_history()
                    self.input.focus_set()
        except Empty:
            pass
        if not self.closing:
            self.drain_timer = self.root.after(80, self._drain)

    def _close(self):
        if self.busy:
            messagebox.showinfo("Execução em andamento", "Conclua a aprovação e aguarde a execução antes de fechar.", parent=self.root)
            return
        self.closing = True
        self.root.after_cancel(self.start_timer)
        self.root.after_cancel(self.drain_timer)
        self.orb.set_active(False)
        self._reset_agent()
        self.copilot_client.close()
        self.runtime.close()
        self.history.close()
        self.root.destroy()


def main():
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=f"{APP_NAME}: chat local")
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    parser.add_argument("--config", default=str(base / "config.yaml"))
    args = parser.parse_args()
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    configure_app_identity()
    root = tk.Tk()
    try:
        DesktopApp(root, args.config)
    except (OSError, ValueError, sqlite3.Error) as error:
        messagebox.showerror("KnightAgent", str(error), parent=root)
        root.destroy()
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
