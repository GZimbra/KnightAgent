from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from knightagent.cli.main import main
from knightagent.providers.base import ProviderError


class KnowledgeCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.yaml"
        self.path.write_text(
            "ollama:\n  model: local-test\nknowledge:\n  enabled: true\n  max_chars: 2200\n",
            encoding="utf-8",
        )
        self.knowledge = Mock()
        patcher = patch("knightagent.cli.main.KnowledgeBase", return_value=self.knowledge)
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        provider_patcher = patch("knightagent.cli.main.build_providers")
        self.build_providers = provider_patcher.start()
        self.addCleanup(provider_patcher.stop)
        agent_patcher = patch("knightagent.cli.main.Agent")
        self.agent = agent_patcher.start()
        runtime_patcher = patch("knightagent.cli.main.OllamaRuntime")
        self.runtime_factory = runtime_patcher.start()
        self.runtime = self.runtime_factory.return_value
        self.addCleanup(runtime_patcher.stop)
        self.addCleanup(agent_patcher.stop)

    def run_cli(self, *arguments):
        output = io.StringIO()
        with patch("sys.argv", ["knightagent", "--config", str(self.path), *arguments]), redirect_stdout(output):
            code = main()
        return code, output.getvalue()

    def test_status_reports_stored_counts_without_loading_providers(self):
        stats = {"documents": 40, "chunks": 250, "official_documents": 28,
                 "bundled_documents": 12, "families": {"python": {"documents": 30, "chunks": 210}}}
        self.knowledge.stats.return_value = stats
        code, output = self.run_cli("knowledge", "status")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), stats)
        self.factory.assert_called_once_with(self.path.resolve().parent / "knightagent-knowledge.sqlite3")
        self.knowledge.close.assert_called_once()
        self.knowledge.sync_official.assert_not_called()
        self.build_providers.assert_not_called()
        self.agent.assert_not_called()

    def test_search_is_offline_and_uses_configured_context_limit(self):
        self.knowledge.search.return_value = "[VBA] Range.Value2 permite leitura e escrita em bloco."
        code, output = self.run_cli("knowledge", "search", "macro VBA copiar células")
        self.assertEqual(code, 0)
        self.assertIn("Range.Value2", output)
        self.knowledge.search.assert_called_once_with("macro VBA copiar células", max_chars=2200)
        self.knowledge.sync_official.assert_not_called()
        self.build_providers.assert_not_called()
        self.knowledge.close.assert_called_once()

    def test_empty_search_reports_no_results(self):
        self.knowledge.search.return_value = ""
        code, output = self.run_cli("knowledge", "search", "assunto ausente")
        self.assertEqual(code, 0)
        self.assertIn("Nenhuma referencia encontrada", output)

    def test_import_uses_only_local_files_and_never_starts_runtime(self):
        report = {"documents_imported": 2, "documents_failed": 0, "documents_skipped": 0,
                  "families": {"python": {"imported": 2}}, "failures": []}
        self.knowledge.import_local.return_value = report
        code, output = self.run_cli("knowledge", "import", "one.txt", "two.md", "--family", "python")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), report)
        self.knowledge.import_local.assert_called_once_with(["one.txt", "two.md"], family="python")
        self.knowledge.close.assert_called_once()
        self.build_providers.assert_not_called()
        self.runtime_factory.assert_not_called()

    def test_import_failure_reports_nonzero_exit(self):
        self.knowledge.import_local.return_value = {"documents_imported": 1, "documents_failed": 1}
        code, output = self.run_cli("knowledge", "import", "one.txt", "missing.txt")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["documents_imported"], 1)
        self.runtime_factory.assert_not_called()

    def test_status_and_search_never_start_ollama(self):
        self.knowledge.stats.return_value = {"documents": 12}
        self.knowledge.search.return_value = "doc"
        self.run_cli("knowledge", "status")
        self.run_cli("knowledge", "search", "Python")
        self.runtime_factory.assert_not_called()

    def test_online_commands_no_longer_exist(self):
        from contextlib import redirect_stderr
        for args in (("knowledge", "sync"), ("key", "set", "openai"),
                     ("test-connection", "openai"), ("test-connection", "copilot")):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                self.run_cli(*args)
            self.assertEqual(result.exception.code, 2)
        self.runtime_factory.assert_not_called()

    def test_library_failure_does_not_print_private_exception_details(self):
        self.knowledge.stats.side_effect = OSError("PRIVATE-PATH-DETAIL")
        code, output = self.run_cli("knowledge", "status")
        self.assertEqual(code, 1)
        self.assertIn("OSError", output)
        self.assertNotIn("PRIVATE-PATH-DETAIL", output)
        self.knowledge.close.assert_called_once()

    def test_local_connection_starts_runtime_before_provider_and_closes_both(self):
        provider = Mock()
        provider.test_connection.return_value = "Modelo local disponivel."
        calls = []
        def start():
            calls.append("start")
            self.runtime_factory.call_args.args[0]["ollama"]["url"] = "http://127.0.0.1:15151"
        def build(config, name):
            calls.append("build")
            self.assertEqual(config["ollama"]["url"], "http://127.0.0.1:15151")
            self.assertEqual(name, "ollama")
            return provider
        self.runtime.start.side_effect = start
        with patch("knightagent.cli.main.build_provider", side_effect=build):
            code, output = self.run_cli("test-connection")
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["start", "build"])
        self.assertIn("disponivel", output)
        provider.close.assert_called_once()
        self.runtime.close.assert_called_once()
        self.build_providers.assert_not_called()
        self.factory.assert_not_called()

    def test_runtime_start_failure_is_reported_and_closed(self):
        self.runtime.start.side_effect = ProviderError("Ollama local indisponivel.")
        code, output = self.run_cli("test-connection", "ollama")
        self.assertEqual(code, 1)
        self.assertIn("indisponivel", output)
        self.runtime.close.assert_called_once()

    def test_model_preparation_starts_and_closes_runtime_without_loading_chat(self):
        with patch("knightagent.cli.main.create_automation_model", return_value={"model": "local"}) as prepare:
            code, output = self.run_cli("knowledge", "prepare-model", "--base", "base:7b")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), {"model": "local"})
        self.assertEqual(prepare.call_args.kwargs["base"], "base:7b")
        self.runtime.start.assert_called_once()
        self.runtime.close.assert_called_once()
        self.factory.assert_not_called()
        self.build_providers.assert_not_called()

    def test_chat_starts_and_closes_runtime_and_always_attaches_knowledge(self):
        provider = Mock()
        self.build_providers.return_value = ({"ollama": provider}, {"planner": "ollama"})
        with patch("builtins.input", return_value="/sair"):
            code, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.runtime.start.assert_called_once()
        self.runtime.close.assert_called_once()
        self.assertIs(self.agent.call_args.kwargs["knowledge"], self.knowledge)
        provider.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
