from copy import deepcopy
from pathlib import Path
import tempfile
from threading import Event
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from knightagent.gui.main import DesktopApp


class RuntimeGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.yaml"
        self.path.write_text("ollama:\n  model: local-test\n", encoding="utf-8")
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.runtimes = []
        self.created = Mock()

        def create_runtime(*args):
            runtime = Mock()
            self.runtimes.append(runtime)
            self.created(runtime)
            return runtime

        runtime_factory = patch("knightagent.gui.main.OllamaRuntime", side_effect=create_runtime)
        self.factory = runtime_factory.start()
        self.addCleanup(runtime_factory.stop)
        client_factory = patch("knightagent.gui.main.CopilotClient")
        self.copilot_factory = client_factory.start()
        self.addCleanup(client_factory.stop)
        self.app = DesktopApp(self.root, self.path)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if not self.app.closing:
            self.app.busy = False
            self.app._close()
        if self.app.runtime_thread:
            self.app.runtime_thread.join(2)
        self.assertEqual(self.errors, [])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(predicate(), "A inicialização assíncrona não concluiu.")

    def test_app_start_preloads_once_and_keeps_input_disabled_until_ready(self):
        entered, release = Event(), Event()
        self.addCleanup(release.set)

        def prepare(runtime):
            def preload():
                entered.set()
                release.wait(3)
            runtime.preload.side_effect = preload
        self.created.side_effect = prepare
        self.wait_for(entered.is_set)
        self.assertTrue(self.app.starting)
        self.assertFalse(self.app.runtime_ready)
        self.assertEqual(str(self.app.input.cget("state")), "disabled")
        runtime = self.runtimes[-1]
        runtime.start.assert_called_once_with()
        runtime.preload.assert_called_once_with()
        self.app._start_runtime()
        self.assertEqual(len(self.runtimes), 2)
        release.set()
        self.wait_for(lambda: self.app.runtime_ready)
        self.assertFalse(self.app.starting)
        self.assertEqual(str(self.app.input.cget("state")), "normal")
        self.assertEqual(self.app.history.list(), [])

    def test_preload_error_keeps_chat_unsent_and_allows_retry(self):
        def prepare(runtime):
            runtime.preload.side_effect = RuntimeError("Modelo local ausente")
        self.created.side_effect = prepare
        self.wait_for(lambda: "Modelo local ausente" in self.app.status.get())
        self.assertFalse(self.app.starting)
        self.assertFalse(self.app.runtime_ready)
        self.assertEqual(str(self.app.input.cget("state")), "normal")
        self.app.input.insert("1.0", "pedido ainda não enviado")
        self.created.side_effect = None
        self.app._send()
        self.wait_for(lambda: self.app.runtime_ready)
        self.assertIn("pedido ainda não enviado", self.app.input.get("1.0", "end"))
        self.assertEqual(self.app.history.list(), [])
        self.assertFalse(self.app.busy)

    def test_start_error_does_not_preload_and_can_be_closed(self):
        def prepare(runtime):
            runtime.start.side_effect = RuntimeError("Bloqueio de rede não confirmado")
        self.created.side_effect = prepare
        self.wait_for(lambda: "Bloqueio de rede" in self.app.status.get())
        runtime = self.runtimes[-1]
        runtime.preload.assert_not_called()
        self.assertFalse(self.app.runtime_ready)
        self.app._close()
        runtime.close.assert_called_once_with()

    def test_close_during_start_cancels_runtime_before_preload(self):
        entered, release = Event(), Event()
        self.addCleanup(release.set)

        def prepare(runtime):
            def start():
                entered.set()
                release.wait(3)
            runtime.start.side_effect = start
            runtime.close.side_effect = release.set
        self.created.side_effect = prepare
        self.wait_for(entered.is_set)
        runtime = self.runtimes[-1]
        self.app._close()
        self.app.runtime_thread.join(2)
        self.assertFalse(self.app.runtime_thread.is_alive())
        runtime.preload.assert_not_called()
        self.assertGreaterEqual(runtime.close.call_count, 1)

    def test_close_during_runtime_creation_never_starts_replacement(self):
        entered, release = Event(), Event()
        self.addCleanup(release.set)

        def constructing(runtime):
            entered.set()
            release.wait(3)
        self.created.side_effect = constructing
        self.wait_for(entered.is_set)
        replacement = self.runtimes[-1]
        self.app._close()
        release.set()
        self.app.runtime_thread.join(2)
        self.assertFalse(self.app.runtime_thread.is_alive())
        replacement.start.assert_not_called()
        replacement.preload.assert_not_called()
        replacement.close.assert_called_once_with()

    def test_close_during_preload_closes_runtime_and_finishes_worker(self):
        entered, release = Event(), Event()
        self.addCleanup(release.set)

        def prepare(runtime):
            def preload():
                entered.set()
                release.wait(3)
            runtime.preload.side_effect = preload
            runtime.close.side_effect = release.set
        self.created.side_effect = prepare
        self.wait_for(entered.is_set)
        runtime = self.runtimes[-1]
        self.app._close()
        self.app.runtime_thread.join(2)
        self.assertFalse(self.app.runtime_thread.is_alive())
        self.assertTrue(self.app.closing)
        runtime.close.assert_called_once_with()

    def test_copilot_only_settings_do_not_reload_ready_model(self):
        self.wait_for(lambda: self.app.runtime_ready)
        saved = deepcopy(self.app.config)
        saved["complementary"]["copilot"] = True
        runtime = self.app.runtime
        self.app._settings_saved(saved, self.path)
        self.assertIs(self.app.runtime, runtime)
        self.assertEqual(len(self.runtimes), 2)
        runtime.preload.assert_called_once_with()
        self.assertTrue(self.app.runtime_ready)
        self.assertEqual(self.app.copilot_button.winfo_manager(), "pack")

    def test_copilot_shortcut_opens_account_section_without_login(self):
        self.wait_for(lambda: self.app.runtime_ready)
        self.app._show_copilot()
        self.assertIsNone(self.app.settings_window)
        saved = deepcopy(self.app.config)
        saved["complementary"]["copilot"] = True
        self.app._settings_saved(saved, self.path)
        account_client = Mock()
        account_client.status.return_value = {"status": "disconnected", "message": "Nenhuma conta conectada."}
        with patch("knightagent.gui.settings.CopilotClient", return_value=account_client), \
                patch("knightagent.gui.settings.SettingsPanel.refresh_models"), \
                patch("knightagent.gui.settings.SettingsPanel.refresh_knowledge"):
            self.app.copilot_button.invoke()
            self.root.update_idletasks()
            self.assertTrue(self.app.settings_window.winfo_exists())
            self.assertEqual(self.app.settings_panel.section_var.get(), "complementary")
            self.assertEqual(self.app.settings_panel.pages["complementary"].winfo_manager(), "pack")
            self.wait_for(lambda: not self.app.settings_panel.copilot_operation)
        account_client.status.assert_called_once_with()
        account_client.login.assert_not_called()
        account_client.verify_access.assert_not_called()
        self.copilot_factory.return_value.login.assert_not_called()
