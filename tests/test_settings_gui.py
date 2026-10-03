import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from knightagent.agent.memory import MemoryStore
from knightagent.config.settings import load
from knightagent.gui.main import DesktopApp


class SettingsGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.yaml"
        self.path.write_text('ollama:\n  model: local-test\n', encoding="utf-8")
        self.root = tk.Tk()
        self.root.withdraw()
        for name in ("refresh_models", "refresh_knowledge"):
            patcher = patch("knightagent.gui.settings.SettingsPanel." + name, return_value=False)
            patcher.start()
            self.addCleanup(patcher.stop)
        runtime = patch("knightagent.gui.main.OllamaRuntime")
        runtime.start()
        self.addCleanup(runtime.stop)
        startup = patch.object(DesktopApp, "_start_runtime")
        startup.start()
        self.addCleanup(startup.stop)
        self.copilot = Mock()
        self.copilot.status.return_value = {"status": "disconnected", "message": "Nenhuma conta conectada."}
        client = patch("knightagent.gui.settings.CopilotClient", return_value=self.copilot)
        self.client_factory = client.start()
        self.addCleanup(client.stop)
        self.app = DesktopApp(self.root, self.path)
        self.app.starting = False
        self.addCleanup(self.destroy_root)
        self.app._show_settings()
        self.app.settings_window.withdraw()
        self.panel = self.app.settings_panel
        self.root.update_idletasks()
        deadline = time.monotonic() + 2
        while self.panel.copilot_operation and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.panel.copilot_operation)

    def destroy_root(self):
        self.app._close()

    def test_settings_attached_to_layout_and_scrollable(self):
        self.assertEqual(self.panel.winfo_manager(), "pack")
        self.assertEqual(self.panel.content.winfo_manager(), "canvas")
        self.assertEqual(self.panel.save_button.winfo_manager(), "pack")
        self.root.update_idletasks()
        self.assertEqual(self.panel.section_var.get(), "local")
        self.assertEqual(set(self.panel.pages), {"local", "complementary", "knowledge", "data"})
        self.assertFalse(hasattr(self.panel, "user_vars"))
        self.assertFalse(hasattr(self.panel, "provider_vars"))
        self.assertFalse(hasattr(self.panel, "role_vars"))
        self.assertFalse(hasattr(self.panel, "knowledge_var"))
        self.assertFalse(self.panel.copilot_var.get())

    def test_sections_preserve_edits_and_show_only_selected_content(self):
        self.panel.copilot_var.set(True)
        for key, button in self.panel.nav_buttons.items():
            button.invoke()
            self.root.update_idletasks()
            self.assertEqual(self.panel.section_var.get(), key)
            visible = [name for name, page in self.panel.pages.items() if page.winfo_manager()]
            self.assertEqual(visible, [key])
        self.assertTrue(self.panel.copilot_var.get())

    def test_complementary_is_opt_in_and_account_setup_has_no_password(self):
        self.panel.show_section("complementary")
        self.assertFalse(self.panel.copilot_login_button.instate(["disabled"]))
        self.assertTrue(self.panel.copilot_logout_button.instate(["disabled"]))
        self.assertTrue(self.panel.copilot_verify_button.instate(["disabled"]))
        self.assertFalse(self.panel.copilot_admin_var.get())
        self.assertFalse(self.panel.copilot_admin_fields.winfo_manager())
        self.assertEqual(self.panel.copilot_tenant_var.get(), "organizations")
        self.assertFalse(hasattr(self.panel, "launch_copilot"))
        self.panel.copilot_var.set(True)
        self.panel._update_copilot_state()
        self.assertIn("Salve", self.panel.copilot_privacy.get())
        self.panel.copilot_var.set(False)
        self.panel._update_copilot_state()
        self.assertIn("IA local", self.panel.copilot_privacy.get())
        self.copilot.login.assert_not_called()
        self.copilot.verify_access.assert_not_called()

    def test_controls_fit_narrow_window(self):
        window = self.app.settings_window
        window.minsize(850, 640)
        window.geometry("850x640")
        window.deiconify()
        self.root.update()
        for key in self.panel.pages:
            self.panel.show_section(key)
            if key == "complementary":
                self.panel.copilot_admin_var.set(True)
                self.panel._toggle_copilot_admin()
            self.root.update()
            left = self.panel.canvas.winfo_rootx()
            right = left + self.panel.canvas.winfo_width()
            pending = [self.panel.pages[key]]
            while pending:
                widget = pending.pop()
                pending.extend(widget.winfo_children())
                if widget.winfo_ismapped():
                    self.assertGreaterEqual(widget.winfo_rootx(), left, (key, str(widget)))
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), right, (key, str(widget)))

    @patch("knightagent.gui.settings.messagebox.showinfo")
    @patch("knightagent.gui.settings.messagebox.showerror")
    def test_save_resources_and_copilot_without_user_or_providers(self, error, info):
        self.panel.level_var.set("baixo")
        self.panel.config["knowledge"]["enabled"] = False
        self.panel.copilot_var.set(True)
        self.panel.copilot_client_id_var.set("12345678-1234-1234-1234-123456789abc")
        self.panel.copilot_tenant_var.set("87654321-1234-1234-1234-123456789abc")
        self.panel.config["user"] = {"name": "Legacy personal data"}
        self.panel.config["providers"] = {"openai": {"enabled": True, "model": "external"}}
        self.panel.config["roles"] = {"planner": "openai"}
        self.panel.save()
        error.assert_not_called()
        saved = load(self.path)
        self.assertNotIn("user", saved)
        self.assertNotIn("providers", saved)
        self.assertEqual(saved["ollama"]["num_ctx"], 4096)
        self.assertEqual(saved["roles"], dict.fromkeys(("planner", "executor", "reviewer"), "ollama"))
        self.assertTrue(saved["complementary"]["copilot"])
        self.assertEqual(saved["complementary"]["mode"], "account")
        self.assertEqual(saved["complementary"]["client_id"], "12345678-1234-1234-1234-123456789abc")
        self.assertEqual(saved["complementary"]["tenant"], "87654321-1234-1234-1234-123456789abc")
        self.copilot.login.assert_not_called()
        self.assertTrue(saved["knowledge"]["enabled"])
        self.assertEqual(saved["knowledge"]["max_chars"], 6000)
        self.assertNotIn("Legacy personal data", self.path.read_text(encoding="utf-8"))
        self.assertEqual(self.app.config, saved)

    @patch("knightagent.gui.settings.messagebox.showerror")
    def test_cloud_model_cannot_be_saved_even_without_inventory(self, error):
        original = self.path.read_bytes()
        self.panel.model_var.set("gpt-oss:120b-cloud")
        self.panel.save()
        error.assert_called_once()
        self.assertEqual(self.path.read_bytes(), original)

    @patch("knightagent.gui.settings.messagebox.showerror")
    def test_uninstalled_model_cannot_be_saved(self, error):
        original = self.path.read_bytes()
        self.panel.models = {"local-test": "3B"}
        self.panel.model_var.set("missing-model")
        self.panel.save()
        error.assert_called_once()
        self.assertEqual(self.path.read_bytes(), original)

    @patch("knightagent.gui.main.messagebox.askyesno", return_value=True)
    @patch("knightagent.gui.main.messagebox.showinfo")
    def test_clear_history_and_memory_are_independent(self, info, confirm):
        store = MemoryStore(self.path.parent / "knightagent-memory.sqlite3")
        db = store._open()
        with db:
            db.execute("INSERT INTO examples(workspace, request, summary, files) VALUES('x', 'macro', 'ok', '[]')")
        db.close()
        self.app.agent = Mock(dialog=["private conversation"])
        self.app.chat_id = self.app.history.create(self.temp.name, "private conversation")
        self.app.history.append(self.app.chat_id, "user", "private conversation")
        self.app.restored_dialog = [("usuario", "private conversation")]
        self.app.input.insert("end", "private conversation")
        self.panel.clear_button.invoke()
        self.assertIsNone(self.app.agent)
        self.assertEqual(self.app.history.list(), [])
        self.assertEqual(self.app.restored_dialog, [])
        self.assertEqual(self.app.chat_list.size(), 0)
        self.assertNotIn("private conversation", self.app.input.get("1.0", "end"))
        self.assertEqual(len(store.recall("macro", "x")), 1)
        self.app.input.insert("end", "preserve chat")
        self.app.chat_id = self.app.history.create(self.temp.name, "preserve chat")
        self.panel.reset_button.invoke()
        self.assertEqual(store.recall("macro", "x"), [])
        self.assertIn("preserve chat", self.app.input.get("1.0", "end"))
        self.assertEqual(self.app.history.list()[0]["title"], "preserve chat")

    @patch("knightagent.gui.settings.messagebox.showinfo")
    @patch("knightagent.gui.main.messagebox.askyesno", return_value=False)
    def test_cancel_and_busy_preserve_chat(self, confirm, info):
        self.app.input.insert("end", "keep")
        self.panel.clear_button.invoke()
        self.assertIn("keep", self.app.input.get("1.0", "end"))
        confirm.assert_called_once()
        confirm.reset_mock()
        self.app.busy = True
        try:
            self.panel.clear_button.invoke()
            self.panel.reset_button.invoke()
            self.panel.save()
            confirm.assert_not_called()
            self.assertEqual(info.call_count, 3)
        finally:
            self.app.busy = False
