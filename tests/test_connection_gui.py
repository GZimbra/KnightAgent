from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from knightagent.config.settings import load
from knightagent.gui import theme
from knightagent.gui.settings import SettingsPanel


class ConnectionGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.yaml"
        self.path.write_text("ollama:\n  model: local-test\n", encoding="utf-8")
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        theme.apply_theme(self.root)
        for name in ("refresh_models", "refresh_knowledge"):
            patcher = patch.object(SettingsPanel, name, return_value=False)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.saved = Mock()
        self.copilot = Mock()
        self.copilot.status.return_value = {"status": "disconnected", "message": "Nenhuma conta conectada."}
        self.copilot.login.return_value = {"status": "authenticated", "account": "usuario@contoso.com", "message": "Conta conectada. Verifique o acesso."}
        self.copilot.logout.return_value = {"status": "disconnected", "message": "Conta desconectada."}
        self.copilot.verify_access.return_value = {"status": "ready", "account": "usuario@contoso.com", "message": "Acesso verificado."}
        client = patch("knightagent.gui.settings.CopilotClient", return_value=self.copilot)
        self.client_factory = client.start()
        self.addCleanup(client.stop)
        self.busy = False
        self.panel = SettingsPanel(self.root, load(self.path), self.path, self.saved, lambda: self.busy)
        self.panel.pack()
        self.wait_for(lambda: not self.panel.copilot_operation)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(predicate(), "A operação assíncrona não concluiu.")

    def test_account_login_is_async_and_does_not_enable_assistance(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = self.path.read_bytes()

        def login():
            entered.set()
            release.wait(3)
            return {"status": "authenticated", "account": "usuario@contoso.com", "message": "Conta conectada."}

        self.copilot.login.side_effect = login
        self.panel._run_copilot("login")
        self.assertTrue(entered.wait(1))
        self.assertTrue(self.panel.copilot_login_button.instate(["disabled"]))
        self.assertTrue(self.panel.copilot_check.instate(["disabled"]))
        self.panel.show_section("knowledge")
        self.panel._run_copilot("login")
        self.copilot.login.assert_called_once_with()
        release.set()
        self.wait_for(lambda: not self.panel.copilot_operation)
        self.assertEqual(self.panel.copilot_status.get(), "usuario@contoso.com\nConta conectada.")
        self.assertEqual(self.panel.copilot_login_button.cget("text"), "Trocar conta")
        self.assertFalse(self.panel.copilot_login_button.instate(["disabled"]))
        self.assertFalse(self.panel.copilot_var.get())
        self.assertEqual(self.panel.copilot_account_status, "authenticated")
        self.copilot.verify_access.assert_not_called()
        self.assertEqual(self.path.read_bytes(), original)
        self.saved.assert_not_called()

    def test_login_setup_required_exposes_public_admin_fields(self):
        self.copilot.login.return_value = {"status": "setup_required", "message": "Solicite o ID do aplicativo à TI."}
        self.panel._run_copilot("login")
        self.wait_for(lambda: not self.panel.copilot_operation)
        self.assertIn("TI", self.panel.copilot_status.get())
        self.assertTrue(self.panel.copilot_admin_var.get())
        self.assertEqual(self.panel.copilot_admin_fields.winfo_manager(), "pack")
        self.assertFalse(self.panel.copilot_login_button.instate(["disabled"]))

    def test_verify_then_disconnect_updates_controls(self):
        self.panel._run_copilot("login")
        self.wait_for(lambda: not self.panel.copilot_operation)
        self.assertFalse(self.panel.copilot_verify_button.instate(["disabled"]))
        self.panel.copilot_verify_button.invoke()
        self.wait_for(lambda: not self.panel.copilot_operation)
        self.assertEqual(self.panel.copilot_account_status, "ready")
        self.copilot.verify_access.assert_called_once_with()
        self.panel.copilot_logout_button.invoke()
        self.wait_for(lambda: not self.panel.copilot_operation)
        self.assertEqual(self.panel.copilot_account, "")
        self.assertTrue(self.panel.copilot_verify_button.instate(["disabled"]))
        self.assertEqual(self.panel.copilot_login_button.cget("text"), "Entrar com conta Microsoft")

    def test_login_failure_is_reported_without_unexpected_exception_details(self):
        self.copilot.login.side_effect = OSError("PRIVATE-TOKEN")
        self.panel._run_copilot("login")
        self.wait_for(lambda: not self.panel.copilot_operation)
        self.assertIn("Tente novamente", self.panel.copilot_status.get())
        self.assertNotIn("PRIVATE-TOKEN", self.panel.copilot_status.get())
        self.assertFalse(self.panel.copilot_login_button.instate(["disabled"]))

    def test_busy_application_prevents_account_changes(self):
        self.busy = True
        self.panel._update_copilot_state()
        self.panel._run_copilot("login")
        self.copilot.login.assert_not_called()
        self.assertTrue(self.panel.copilot_login_button.instate(["disabled"]))
        self.busy = False
        self.panel._update_copilot_state()
        self.assertFalse(self.panel.copilot_login_button.instate(["disabled"]))

    def test_account_switch_keeps_previous_session_until_login_succeeds(self):
        self.panel._run_copilot("login")
        self.wait_for(lambda: not self.panel.copilot_operation)
        self.copilot.login.return_value = {"status": "error", "message": "Login cancelado. Tente novamente."}
        self.panel.copilot_login_button.invoke()
        self.wait_for(lambda: not self.panel.copilot_operation)
        self.assertEqual(self.copilot.login.call_count, 2)
        self.copilot.logout.assert_not_called()
        self.assertEqual(self.panel.copilot_account, "usuario@contoso.com")
        self.assertIn("Login cancelado", self.panel.copilot_status.get())
        self.assertFalse(self.panel.copilot_logout_button.instate(["disabled"]))

    def test_destroy_closes_client_during_pending_login(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def login():
            entered.set()
            release.wait(3)
            return {"status": "authenticated", "message": "Conta conectada."}

        self.copilot.login.side_effect = login
        self.panel._run_copilot("login")
        self.assertTrue(entered.wait(1))
        self.panel.destroy()
        self.copilot.close.assert_called_once_with()
        release.set()
        self.root.update()

    def test_import_reports_partial_result_and_keeps_interface_responsive(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        knowledge = Mock()
        selected = (self.path.parent / "guia.txt", self.path.parent / "exemplo.md")

        def import_local(paths, *, family, progress):
            self.assertEqual(paths, selected)
            self.assertEqual(family, "local")
            progress("Lendo documentação local…")
            entered.set()
            release.wait(3)
            return {"documents_imported": 12, "documents_failed": 1, "documents_skipped": 2}

        knowledge.import_local.side_effect = import_local
        knowledge.stats.return_value = {"documents": 20, "chunks": 80,
                                        "bundled_documents": 8, "local_documents": 12}
        with patch("knightagent.gui.settings.KnowledgeBase", return_value=knowledge) as factory, \
                patch("knightagent.gui.settings.filedialog.askopenfilenames", return_value=selected) as dialog:
            self.assertFalse(hasattr(self.panel, "knowledge_var"))
            self.panel.import_knowledge()
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.panel.import_button.instate(["disabled"]))
            self.panel.show_section("complementary")
            self.wait_for(lambda: "Lendo" in self.panel.knowledge_progress.get())
            self.panel.import_knowledge()
            knowledge.import_local.assert_called_once()
            dialog.assert_called_once()
            release.set()
            self.wait_for(lambda: not self.panel.importing_knowledge)
            factory.assert_called_once_with(self.path.parent / "knightagent-knowledge.sqlite3")
        self.assertIn("Importação parcial", self.panel.knowledge_progress.get())
        self.assertIn("2 documentos ignorados", self.panel.knowledge_progress.get())
        self.assertIn("20 documentos", self.panel.knowledge_status.get())
        self.assertFalse(self.panel.import_button.instate(["disabled"]))
        knowledge.close.assert_called_once()

    def test_import_cancel_does_not_open_database(self):
        with patch("knightagent.gui.settings.KnowledgeBase") as knowledge, \
                patch("knightagent.gui.settings.filedialog.askopenfilenames", return_value=()):
            self.panel.import_knowledge()
        knowledge.assert_not_called()
        self.assertFalse(self.panel.importing_knowledge)
        self.assertFalse(self.panel.import_button.instate(["disabled"]))

    def test_import_failure_reenables_button_without_exposing_raw_error(self):
        knowledge = Mock()
        knowledge.import_local.side_effect = RuntimeError("PRIVATE-DETAIL")
        with patch("knightagent.gui.settings.KnowledgeBase", return_value=knowledge):
            self.panel.import_knowledge([self.path.parent / "guia.md"])
            self.wait_for(lambda: not self.panel.importing_knowledge)
        self.assertIn("Falha", self.panel.knowledge_progress.get())
        self.assertNotIn("PRIVATE-DETAIL", self.panel.knowledge_progress.get())
        self.assertFalse(self.panel.import_button.instate(["disabled"]))
        knowledge.close.assert_called_once()
