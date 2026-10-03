import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import httpx

from knightagent.providers.base import ProviderError
from knightagent.runtime import OllamaRuntime, _local_path, _server_environment, find_ollama


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "config.yaml"
        self.config = {"ollama": {"model": "local", "num_ctx": 4096}, "timeout": 2}
        self.executable = self.root / "runtime" / "ollama" / ("ollama.exe" if os.name == "nt" else "ollama")
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"fixture")
        self.runtime = OllamaRuntime(self.config, self.path)
        self.addCleanup(self.runtime.close)
        self.process = Mock()
        self.process.poll.return_value = None
        self.job = Mock()
        self.client = Mock()
        self.client.__enter__ = Mock(return_value=self.client)
        self.client.__exit__ = Mock(return_value=False)
        self.client.get.return_value = httpx.Response(200, json={"models": []})
        patches = {
            "knightagent.runtime.subprocess.Popen": self.process,
            "knightagent.runtime._WindowsJob": self.job,
            "knightagent.runtime.httpx.Client": self.client,
            "knightagent.runtime._free_port": 43125,
            "knightagent.network_guard.assert_offline_firewall": None,
        }
        self.mocks = {}
        for name, result in patches.items():
            patcher = patch(name, return_value=result)
            self.mocks[name.rsplit(".", 1)[-1]] = patcher.start()
            self.addCleanup(patcher.stop)
        self.logs = 'msg="Listening on 127.0.0.1:43125 (version 0.17.0)"\nmsg="Ollama cloud disabled: true"'

    def test_prefers_shipped_runtime(self):
        self.assertEqual(find_ollama(self.path), self.executable)

    def test_network_models_paths_are_rejected_before_any_filesystem_access(self):
        for path in (r"\\server\models", "//server/models", "https://server/models"):
            with self.subTest(path=path), patch.object(Path, "lstat") as stat_call:
                with self.assertRaises(ValueError):
                    _local_path(path)
                stat_call.assert_not_called()

    def test_mapped_drive_is_rejected_before_filesystem_access(self):
        if os.name != "nt":
            self.skipTest("Windows mapped drive")
        with patch("knightagent.runtime.ctypes.windll.kernel32.GetDriveTypeW", return_value=4), \
                patch.object(Path, "lstat") as stat_call:
            with self.assertRaises(ValueError):
                _local_path("Z:/models")
            stat_call.assert_not_called()

    def test_private_child_receives_no_cloud_no_proxy_and_private_identity(self):
        with patch.object(self.runtime, "_log_text", return_value=self.logs):
            self.assertIn("desativados", self.runtime.start())
        self.assertTrue(self.runtime.running)
        args, kwargs = self.mocks["Popen"].call_args
        self.assertEqual(args[0], [str(self.executable), "serve"])
        self.assertEqual(kwargs["env"]["OLLAMA_NO_CLOUD"], "1")
        self.assertEqual(kwargs["env"]["OLLAMA_HOST"], "127.0.0.1:43125")
        self.assertEqual(kwargs["env"]["OLLAMA_NUM_PARALLEL"], "1")
        self.assertEqual(kwargs["env"]["OLLAMA_KEEP_ALIVE"], "-1")
        self.assertNotEqual(kwargs["env"]["USERPROFILE"], os.environ.get("USERPROFILE"))
        self.assertEqual(self.config["ollama"]["url"], "http://127.0.0.1:43125")
        self.client.get.assert_called_once_with("http://127.0.0.1:43125/api/tags")
        self.assertFalse(self.mocks["Client"].call_args.kwargs["trust_env"])

    def test_sensitive_inherited_environment_is_removed(self):
        inherited = {"HTTPS_PROXY": "https://proxy", "http_proxy": "http://proxy", "OPENAI_API_KEY": "PRIVATE",
                     "MICROSOFT_COPILOT_TOKEN": "PRIVATE", "OLLAMA_HOST": "https://ollama.com",
                     "OLLAMA_ORIGINS": "*", "OLLAMA_NO_CLOUD": "0", "OLLAMA_DEBUG": "1"}
        with patch.dict(os.environ, inherited):
            env = _server_environment(self.root, self.root / "models", 12345, self.config)
        for key in inherited:
            if key not in {"OLLAMA_HOST", "OLLAMA_NO_CLOUD"}:
                self.assertNotIn(key, env)
        self.assertEqual(env["OLLAMA_HOST"], "127.0.0.1:12345")
        self.assertEqual(env["OLLAMA_NO_CLOUD"], "1")

    def test_never_reuses_unknown_server_or_unconfirmed_cloud_mode(self):
        for logs in ("", self.logs.replace("43125", "11434"), self.logs.replace("disabled: true", "disabled: false")):
            runtime = OllamaRuntime(self.config, self.path)
            with self.subTest(logs=logs), patch.object(runtime, "_log_text", return_value=logs), \
                    patch("knightagent.runtime.time.monotonic", side_effect=[0, 0, 3]):
                with self.assertRaisesRegex(ProviderError, "nao confirmou"):
                    runtime.start()
            self.assertFalse(runtime.running)
        self.client.get.assert_not_called()

    def test_unconfirmed_firewall_prevents_process_creation(self):
        if os.name != "nt":
            self.skipTest("Windows firewall boundary")
        self.mocks["assert_offline_firewall"].side_effect = RuntimeError("bloqueio nao confirmado")
        with self.assertRaisesRegex(RuntimeError, "bloqueio"):
            self.runtime.start()
        self.mocks["Popen"].assert_not_called()

    def test_startup_can_be_cancelled_and_closes_only_owned_child(self):
        errors = []
        spawned = threading.Event()
        def spawn(*args, **kwargs):
            spawned.set()
            return self.process
        self.mocks["Popen"].side_effect = spawn
        def run():
            try:
                self.runtime.start()
            except ProviderError as error:
                errors.append(str(error))
        with patch.object(self.runtime, "_log_text", return_value=""):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(spawned.wait(1))
            self.runtime.close()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(self.runtime.running)
        self.assertTrue(errors)
        self.runtime.close()
        if os.name == "nt":
            self.job.close.assert_called_once()
        self.process.terminate.assert_called_once()

    def test_missing_model_does_not_stop_inventory_server(self):
        with patch.object(self.runtime, "_log_text", return_value=self.logs):
            self.runtime.start()
        with patch("knightagent.runtime.OllamaProvider") as provider:
            provider.return_value.preload.side_effect = ProviderError("Modelo ausente")
            with self.assertRaises(ProviderError):
                self.runtime.preload()
            provider.return_value.close.assert_called_once()
        self.assertTrue(self.runtime.running)
