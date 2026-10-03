"""Configurações do aplicativo local e da conta Microsoft Copilot opcional."""

from copy import deepcopy
import os
from pathlib import Path
from queue import Empty, Queue
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from knightagent.gui.buttons import RoundedButton

import httpx
import yaml

from knightagent.config.performance import PROFILES, apply_profile
from knightagent.config.settings import load
from knightagent.copilot_client import CopilotClient
from knightagent.gui import theme
from knightagent.knowledge import KnowledgeBase
from knightagent.offline import is_local_model, validate_local_model, validate_local_url


def installed_models(url, client=None):
    url = validate_local_url(url)
    owns_client = client is None
    client = client or httpx.Client(timeout=5, trust_env=False)
    try:
        response = client.get(url.rstrip("/") + "/api/tags")
        response.raise_for_status()
        models = {}
        for item in response.json().get("models", []):
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not is_local_model(item):
                continue
            name = item.get("name")
            details = item.get("details") or {}
            models[name] = str(details.get("parameter_size", "desconhecido")) if isinstance(details, dict) else "desconhecido"
        return models
    finally:
        if owns_client:
            client.close()


class SettingsPanel(ttk.Frame):
    def __init__(self, parent, config, config_path, on_save, is_busy, on_clear_history=None, on_reset_memory=None, copilot_client=None):
        super().__init__(parent, padding=18)
        self.config = config
        self.config_path = Path(config_path)
        self.on_save = on_save
        self.is_busy = is_busy
        self.on_clear_history = on_clear_history
        self.on_reset_memory = on_reset_memory
        self.results = Queue()
        self.models = {}
        self.model_var = tk.StringVar(value=config["ollama"]["model"])
        self.level_var = tk.StringVar(value=config["performance"]["level"])
        self.memory_var = tk.BooleanVar(value=config["memory"]["enabled"])
        self.knowledge_status = tk.StringVar(value="Consultando a biblioteca local…")
        self.knowledge_progress = tk.StringVar()
        self.knowledge_path = self.config_path.parent / "knightagent-knowledge.sqlite3"
        self.importing_knowledge = False
        self.model_size = tk.StringVar(value="Parâmetros do modelo: consultar Ollama")
        self.profile_text = tk.StringVar()
        complementary = config.get("complementary", {})
        self.copilot_var = tk.BooleanVar(value=complementary.get("copilot", False) if complementary.get("mode") == "account" else False)
        self.copilot_client_id_var = tk.StringVar(value=complementary.get("client_id", ""))
        self.copilot_tenant_var = tk.StringVar(value=complementary.get("tenant", "organizations"))
        self.copilot_admin_var = tk.BooleanVar(value=False)
        self.copilot_status = tk.StringVar(value="Consultando a conta salva neste computador…")
        self.copilot_privacy = tk.StringVar()
        self.copilot_operation = False
        self.copilot_account = ""
        self.copilot_account_status = "disconnected"
        self._disposed = False
        self._copilot_settings = self._complementary_settings()
        self.copilot_client = copilot_client if copilot_client is not None else CopilotClient(self.config_path, self._copilot_settings)
        self._build()
        self._update_profile()
        self.drain_timer = self.after(100, self._drain)
        self.bind("<Destroy>", self._destroy_timer, add="+")
        self.refresh_models()
        self.refresh_knowledge()
        self._run_copilot("status")

    def _build(self):
        self.pages = {}
        self.nav_buttons = {}
        self.section_var = tk.StringVar(value="local")
        ttk.Label(self, text="Configurações", font=(theme.UI_FONT, 22, "bold")).pack(anchor="w")
        ttk.Label(self, text="Escolha uma seção para ajustar o KnightAgent.", style="Muted.TLabel").pack(anchor="w", pady=(4, 20))
        footer = ttk.Frame(self)
        footer.pack(side="bottom", fill="x", pady=(16, 0))
        ttk.Label(footer, text="Salvar aplica as alterações de todas as seções.", style="Muted.TLabel",
                  wraplength=340).pack(side="left", padx=(0, 12))
        self.save_button = RoundedButton(footer, text="Salvar configurações", command=self.save, style="Accent.TButton")
        self.save_button.pack(side="right")
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        navigation = ttk.Frame(body, padding=(0, 0, 20, 0))
        navigation.pack(side="left", fill="y")
        for key, label in (("local", "IA local"), ("complementary", "Copilot"),
                           ("knowledge", "Biblioteca"), ("data", "Dados locais")):
            button = ttk.Radiobutton(navigation, text=label, variable=self.section_var, value=key,
                                     style="SettingsNav.TRadiobutton", command=lambda key=key: self.show_section(key))
            button.pack(fill="x", pady=(0, 6))
            self.nav_buttons[key] = button
        viewport = ttk.Frame(body)
        viewport.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(viewport, bg=theme.BLACK, highlightthickness=0, width=1)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.content = ttk.Frame(self.canvas, padding=(0, 0, 12, 0))
        window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))

        self._page("local", "IA local", "O Ollama inicia junto com o aplicativo e trabalha somente neste computador.")
        model_box = self._section("Modelo Ollama")
        self._section_label(model_box, text="Modelo instalado").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.model_combo = ttk.Combobox(model_box, textvariable=self.model_var, width=16, state="readonly")
        self.model_combo.grid(row=1, column=0, sticky="ew", padx=(0, 12))
        self.model_combo.bind("<<ComboboxSelected>>", lambda _: self._update_size())
        RoundedButton(model_box, text="Atualizar lista", command=self.refresh_models).grid(row=1, column=1)
        self._section_label(model_box, textvariable=self.model_size, wrap=True).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self._section_label(model_box, text="Somente modelos locais já instalados. A IA usa a biblioteca, a memória e os arquivos locais; não há pesquisa online ou download de modelos no aplicativo.", wrap=True).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        model_box.columnconfigure(0, weight=1)

        profile_box = self._section("Nível de recursos da IA local")
        labels = {"baixo": "Baixo", "medio": "Médio", "alto": "Alto"}
        for column, level in enumerate(PROFILES):
            ttk.Radiobutton(profile_box, text=labels[level], variable=self.level_var,
                            value=level, command=self._update_profile, style="Section.TRadiobutton").grid(row=0, column=column, padx=(0, 18), sticky="w")
            profile_box.columnconfigure(column, weight=1)
        self._section_label(profile_box, textvariable=self.profile_text, wrap=True).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        self._section_label(profile_box, text="Mais contexto e saída usam mais memória e podem demorar mais. O tamanho em parâmetros depende do modelo escolhido.", wrap=True).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        self._page("data", "Dados locais", "Controle o contexto usado pela IA e os dados salvos.")
        memory_box = self._section("Memória da IA")
        ttk.Checkbutton(memory_box, text="Usar exemplos aprovados da memória local", variable=self.memory_var, style="Section.TCheckbutton").pack(anchor="w")
        self._section_label(memory_box, text="SQLite local. Guarda pedidos e trechos de arquivos aprovados para dar contexto a respostas futuras; não altera os pesos do modelo.", wrap=True).pack(fill="x", pady=(12, 0))
        actions = self._section("Gerenciar dados")
        self._section_label(actions, text="As conversas ficam salvas neste computador. Limpar os chats não apaga os exemplos da memória, e vice-versa. Cada ação pede confirmação.", wrap=True).pack(fill="x", pady=(0, 14))
        self.clear_button = RoundedButton(actions, text="Limpar histórico de chats", command=lambda: self._maintenance(self.on_clear_history))
        self.clear_button.pack(anchor="w", pady=(0, 10))
        self.reset_button = RoundedButton(actions, text="Resetar memória local", command=lambda: self._maintenance(self.on_reset_memory))
        self.reset_button.pack(anchor="w")

        self._page("knowledge", "Biblioteca técnica", "Documentação e exemplos de automação consultados pela IA.")
        knowledge_box = self._section("Conhecimento local")
        self._section_label(knowledge_box, text="Fontes locais obrigatórias em todos os pedidos.", wrap=True).pack(fill="x")
        self._section_label(knowledge_box, text="Inclui guias de Python, VBA, Visual Basic e Office Scripts por padrão. A IA recebe os trechos relevantes a cada pedido; os pesos do modelo Ollama não são alterados.", wrap=True).pack(fill="x", pady=(12, 0))
        self._section_label(knowledge_box, textvariable=self.knowledge_status, wrap=True).pack(fill="x", pady=(14, 0))
        import_box = self._section("Adicionar conhecimento")
        self._section_label(import_box, text="Importe arquivos TXT, Markdown ou JSON (UTF-8) deste computador. Os documentos são armazenados na biblioteca local e ficam disponíveis sem internet.", wrap=True).pack(fill="x", pady=(0, 14))
        self.import_button = RoundedButton(import_box, text="Importar documentos locais", command=self.import_knowledge)
        self.import_button.pack(anchor="w")
        self._section_label(import_box, textvariable=self.knowledge_progress, wrap=True).pack(fill="x", pady=(12, 0))

        self._page("complementary", "Microsoft Copilot", "Conecte sua conta para complementar a IA local em segundo plano.")
        copilot_box = self._section("Microsoft Copilot")
        self.copilot_check = ttk.Checkbutton(copilot_box, text="Ativar auxílio automático do Copilot", variable=self.copilot_var,
                                           command=self._update_copilot_state, style="Section.TCheckbutton")
        self.copilot_check.pack(anchor="w")
        self._section_label(copilot_box, textvariable=self.copilot_privacy, wrap=True).pack(fill="x", pady=(12, 0))
        self._section_label(copilot_box, text="Ao ativar e salvar, consultas de auxílio são enviadas à Microsoft pela internet. O Ollama continua local. Entrar na conta, por si só, não ativa o envio de pedidos.", wrap=True).pack(fill="x", pady=(12, 0))

        account_box = self._section("Conta Microsoft")
        self._section_label(account_box, textvariable=self.copilot_status, wrap=True).pack(fill="x", pady=(0, 14))
        self.copilot_login_button = RoundedButton(account_box, text="Entrar com conta Microsoft", command=lambda: self._run_copilot("login"), style="Accent.TButton")
        self.copilot_login_button.pack(anchor="w", pady=(0, 10))
        self.copilot_verify_button = RoundedButton(account_box, text="Verificar acesso", command=lambda: self._run_copilot("verify_access"))
        self.copilot_verify_button.pack(anchor="w", pady=(0, 10))
        self.copilot_logout_button = RoundedButton(account_box, text="Desconectar", command=lambda: self._run_copilot("logout"))
        self.copilot_logout_button.pack(anchor="w")
        self._section_label(account_box, text="O login abre a página oficial da Microsoft. Use sua conta de trabalho com licença Microsoft 365 Copilot. A disponibilidade depende das permissões da organização; a conta do aplicativo Copilot do Windows não garante acesso à integração.", wrap=True).pack(fill="x", pady=(16, 0))

        setup_box = self._section("Configuração da organização")
        self.copilot_admin_check = ttk.Checkbutton(setup_box, text="Mostrar configuração da TI", variable=self.copilot_admin_var,
                                                  command=self._toggle_copilot_admin, style="Section.TCheckbutton")
        self.copilot_admin_check.pack(anchor="w")
        self.copilot_admin_fields = ttk.Frame(setup_box, style="Section.TFrame")
        self._section_label(self.copilot_admin_fields, text="A TI registra e autoriza o aplicativo uma única vez. Com esses dados já preenchidos, cada usuário precisa apenas entrar na própria conta. Não informe senha, chave de API ou segredo do aplicativo.", wrap=True).pack(fill="x", pady=(12, 16))
        self._section_label(self.copilot_admin_fields, text="ID do aplicativo (client ID)").pack(anchor="w", pady=(0, 6))
        self.copilot_client_id_entry = ttk.Entry(self.copilot_admin_fields, textvariable=self.copilot_client_id_var)
        self.copilot_client_id_entry.pack(fill="x", pady=(0, 14))
        self._section_label(self.copilot_admin_fields, text="Organização (tenant)").pack(anchor="w", pady=(0, 6))
        self.copilot_tenant_entry = ttk.Entry(self.copilot_admin_fields, textvariable=self.copilot_tenant_var)
        self.copilot_tenant_entry.pack(fill="x")
        self._section_label(self.copilot_admin_fields, text="Use organizations para organizações autorizadas ou o tenant informado pela TI.", wrap=True).pack(fill="x", pady=(8, 0))
        self._update_copilot_state()
        self._bind_scroll(self.content)
        self.show_section("local")

    def _page(self, key, title, description):
        page = ttk.Frame(self.content)
        self.pages[key] = page
        self._current_page = page
        ttk.Label(page, text=title, font=(theme.UI_FONT, 18, "bold")).pack(anchor="w", pady=(0, 6))
        help_label = ttk.Label(page, text=description, style="Muted.TLabel", wraplength=500)
        help_label.pack(fill="x", pady=(0, 22))
        page.bind("<Configure>", lambda e: help_label.configure(wraplength=max(120, e.width)), add="+")

    def show_section(self, key):
        for page in self.pages.values():
            page.pack_forget()
        self.section_var.set(key)
        self.pages[key].pack(fill="x")
        self.update_idletasks()
        self.canvas.yview_moveto(0)

    def _section(self, title):
        section = ttk.Frame(self._current_page, padding=18, style="Section.TFrame")
        section.pack(fill="x", pady=(0, 16))
        ttk.Label(section, text=title, style="Section.TLabel", font=(theme.UI_FONT, 13, "bold")).pack(anchor="w", pady=(0, 16))
        fields = ttk.Frame(section, style="Section.TFrame")
        fields.pack(fill="x")
        return fields

    @staticmethod
    def _section_label(parent, *, wrap=False, **options):
        label = ttk.Label(parent, style="Section.TLabel", justify="left", **options)
        if wrap:
            # The section owns the available width; font/DPI changes must not
            # turn explanatory text into a wider, clipped settings panel.
            label.configure(wraplength=560)
            parent.bind("<Configure>", lambda event: label.configure(wraplength=max(120, event.width - 36)), add="+")
        return label

    def _bind_scroll(self, widget):
        widget.bind("<MouseWheel>", self._wheel)
        widget.bind("<FocusIn>", self._reveal)
        for child in widget.winfo_children():
            self._bind_scroll(child)

    def _wheel(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def _reveal(self, event):
        widget = event.widget
        top = widget.winfo_rooty() - self.content.winfo_rooty()
        visible_top = self.canvas.canvasy(0)
        if top < visible_top or top + widget.winfo_height() > visible_top + self.canvas.winfo_height():
            self.canvas.yview_moveto(max(0, top - 12) / max(1, self.content.winfo_height()))

    def _maintenance(self, callback):
        if self.is_busy():
            messagebox.showinfo("KnightAgent", "Aguarde o pedido atual terminar antes de limpar os dados.", parent=self)
        elif callback is not None:
            callback()

    def _update_copilot_state(self):
        busy = self.copilot_operation or self.is_busy()
        connected = bool(self.copilot_account) or self.copilot_account_status in {"authenticated", "signed_in", "ready"}
        for control in (self.copilot_login_button, self.copilot_check, self.copilot_admin_check,
                        self.copilot_client_id_entry, self.copilot_tenant_entry):
            control.state(["disabled"] if busy else ["!disabled"])
        self.copilot_verify_button.state(["disabled"] if busy or not connected else ["!disabled"])
        self.copilot_logout_button.state(["disabled"] if busy or not connected else ["!disabled"])
        login_text = "Trocar conta" if connected else "Entrar com conta Microsoft"
        if self.copilot_login_button.cget("text") != login_text:
            self.copilot_login_button.configure(text=login_text)
        if not self.copilot_var.get():
            self.copilot_privacy.set("Auxílio desativado. Os pedidos usam somente a IA local.")
        else:
            self.copilot_privacy.set("Auxílio selecionado. Salve as configurações para usar o Copilot quando a conta tiver acesso autorizado.")

    def _toggle_copilot_admin(self):
        if self.copilot_admin_var.get():
            self.copilot_admin_fields.pack(fill="x")
        else:
            self.copilot_admin_fields.pack_forget()

    def _complementary_settings(self):
        return {"copilot": self.copilot_var.get(), "mode": "account",
                "client_id": self.copilot_client_id_var.get().strip(),
                "tenant": self.copilot_tenant_var.get().strip() or "organizations"}

    def _refresh_copilot_client(self):
        settings = self._complementary_settings()
        if settings != self._copilot_settings:
            replacement = CopilotClient(self.config_path, settings)
            self.copilot_client.close()
            self.copilot_client = replacement
            self._copilot_settings = settings
            self.copilot_account = ""
            self.copilot_account_status = "disconnected"

    def _run_copilot(self, operation):
        if self._disposed or self.copilot_operation or (operation != "status" and self.is_busy()):
            return
        try:
            self._refresh_copilot_client()
        except (RuntimeError, ValueError) as error:
            self.copilot_status.set(str(error))
            return
        self.copilot_operation = True
        self._update_copilot_state()
        messages = {"status": "Consultando a conta salva neste computador…",
                    "login": "Aguardando o login na página oficial da Microsoft…",
                    "logout": "Desconectando esta conta…",
                    "verify_access": "Verificando a licença e o acesso ao Copilot…"}
        self.copilot_status.set(messages[operation])
        client = self.copilot_client

        def work():
            try:
                result = getattr(client, operation)()
            except (RuntimeError, ValueError) as error:
                result = {"status": "error", "message": str(error)}
            except Exception:
                result = {"status": "error", "message": "Não foi possível concluir a operação da conta Microsoft. Tente novamente."}
            self.results.put(("copilot_result", (operation, result)))

        threading.Thread(target=work, daemon=True).start()

    def _update_profile(self):
        level = self.level_var.get()
        values = PROFILES[level]
        self.profile_text.set(f"Contexto: {values['num_ctx']:,} tokens  |  resposta: até {values['num_predict']:,} tokens  |  modelo carregado: {values['keep_alive']}")

    def _update_size(self):
        self.model_size.set("Parâmetros do modelo: " + self.models.get(self.model_var.get(), "desconhecido"))

    def refresh_models(self):
        url = self.config["ollama"].get("url", "http://localhost:11434")
        def work():
            try:
                self.results.put(("models", installed_models(url)))
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                self.results.put(("error", "IA local indisponível. Aguarde a inicialização e atualize a lista."))
        threading.Thread(target=work, daemon=True).start()

    def refresh_knowledge(self):
        path = self.knowledge_path
        def work():
            knowledge = None
            try:
                knowledge = KnowledgeBase(path)
                self.results.put(("knowledge_stats", knowledge.stats()))
            except Exception:
                self.results.put(("knowledge_error", "Não foi possível consultar a biblioteca local."))
            finally:
                if knowledge is not None:
                    knowledge.close()
        threading.Thread(target=work, daemon=True).start()

    def import_knowledge(self, paths=None):
        if self.importing_knowledge:
            return
        if paths is None:
            paths = filedialog.askopenfilenames(
                parent=self, title="Importar documentos para a biblioteca local",
                filetypes=[("Documentos locais", "*.txt *.md *.json"),
                           ("Texto", "*.txt"), ("Markdown", "*.md"), ("JSON", "*.json")],
            )
        if not paths:
            return
        paths = tuple(Path(path) for path in paths)
        self.importing_knowledge = True
        self.import_button.state(["disabled"])
        self.knowledge_progress.set("Importando documentos locais…")
        path = self.knowledge_path

        def work():
            knowledge = None
            try:
                knowledge = KnowledgeBase(path)
                report = knowledge.import_local(paths, family="local", progress=lambda message: self.results.put(("knowledge_progress", message)))
                self.results.put(("knowledge_stats", knowledge.stats()))
                imported, failed = report["documents_imported"], report["documents_failed"]
                skipped = report.get("documents_skipped", 0)
                result = f"Importação concluída: {imported} documentos importados."
                if failed:
                    result = f"Importação parcial: {imported} documentos importados; {failed} falhas. Os documentos já disponíveis foram preservados."
                    details = report.get("failures", [])[:3]
                    for failure in details:
                        result += f"\n{Path(failure['path']).name}: {failure['reason']}"
                if skipped:
                    result += f" {skipped} documentos ignorados."
            except Exception:
                result = "Falha ao importar os documentos. Confira o formato e as permissões dos arquivos; a biblioteca existente continua disponível."
            finally:
                if knowledge is not None:
                    knowledge.close()
            self.results.put(("knowledge_import_done", result))

        threading.Thread(target=work, daemon=True).start()

    def _update_knowledge_stats(self, stats):
        imported = stats["documents"] - stats.get("bundled_documents", 0)
        summary = (
            f"{stats['documents']} documentos · {stats['chunks']} trechos\n"
            f"{stats.get('bundled_documents', 0)} guias incluídos · {imported} documentos adicionados"
        )
        labels = {"python": "Python", "vba": "VBA", "visual_basic": "Visual Basic", "office_scripts": "Office Scripts", "local": "Documentos locais"}
        families = stats.get("families", {})
        if families:
            summary += "\n" + " · ".join(f"{labels.get(name, name)}: {report.get('documents', 0)}"
                                          for name, report in families.items())
        self.knowledge_status.set(summary)

    def _drain(self):
        try:
            while True:
                kind, payload = self.results.get_nowait()
                if kind == "models":
                    self.models = payload
                    self.model_combo.configure(values=list(payload))
                    self._update_size()
                elif kind == "copilot_result":
                    operation, payload = payload
                    self.copilot_operation = False
                    self.copilot_account_status = payload.get("status", "error")
                    previous_account = self.copilot_account if self.copilot_account_status not in {"disconnected", "signed_out", "setup_required"} else ""
                    self.copilot_account = payload.get("account", previous_account)
                    message = payload.get("message", "Não foi possível consultar a conta Microsoft.")
                    self.copilot_status.set(f"{self.copilot_account}\n{message}" if self.copilot_account else message)
                    if self.copilot_account_status == "setup_required" and operation == "login":
                        self.copilot_admin_var.set(True)
                        self._toggle_copilot_admin()
                    self._update_copilot_state()
                elif kind == "knowledge_stats":
                    self._update_knowledge_stats(payload)
                elif kind == "knowledge_error":
                    self.knowledge_status.set(payload)
                elif kind == "knowledge_progress":
                    self.knowledge_progress.set(payload)
                elif kind == "knowledge_import_done":
                    self.importing_knowledge = False
                    self.import_button.state(["!disabled"])
                    self.knowledge_progress.set(payload)
                else:
                    self.model_size.set(payload)
        except Empty:
            pass
        if not self._disposed and self.winfo_exists():
            self._update_copilot_state()
            self.drain_timer = self.after(100, self._drain)

    def _destroy_timer(self, event):
        if event.widget is self:
            self._disposed = True
            self.after_cancel(self.drain_timer)
            self.copilot_client.close()

    def save(self):
        if self.is_busy() or self.copilot_operation:
            messagebox.showinfo("KnightAgent", "Aguarde o pedido atual terminar antes de alterar as configurações.", parent=self)
            return
        try:
            model = validate_local_model(self.model_var.get().strip())
            if self.models and model not in self.models:
                raise ValueError("Selecione um modelo da lista instalada no Ollama.")
            draft = deepcopy(self.config)
            draft.pop("user", None)
            draft.pop("providers", None)
            draft["ollama"]["model"] = model
            apply_profile(draft, self.level_var.get())
            draft["memory"] = {"enabled": self.memory_var.get(), "scope": self.config["memory"]["scope"]}
            draft["knowledge"] = {**self.config.get("knowledge", {}), "enabled": True}
            draft["complementary"] = self._complementary_settings()
            draft["roles"] = dict.fromkeys(("planner", "executor", "reviewer"), "ollama")
            target = self.config_path if self.config_path.suffix.lower() in {".yaml", ".yml"} else self.config_path.with_suffix(".yaml")
            text = yaml.safe_dump(draft, allow_unicode=True, sort_keys=False)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, prefix=".knightagent-", suffix=".yaml", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(text)
                validated = load(temporary)
                os.replace(temporary, target)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
            self.config = validated
            self.config_path = target
            self._refresh_copilot_client()
            self._run_copilot("status")
            self.on_save(validated, target)
            messagebox.showinfo("KnightAgent", "Configurações salvas. O próximo pedido usará os novos valores.", parent=self)
        except (OSError, ValueError, yaml.YAMLError) as error:
            messagebox.showerror("KnightAgent", str(error), parent=self)
