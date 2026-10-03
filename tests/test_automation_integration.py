import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from knightagent.agent.loop import Agent
from knightagent.agent.memory import MemoryStore
from knightagent.automation_model import create_automation_model
from knightagent.config.settings import load, build_providers
from knightagent.knowledge import KnowledgeBase, SPECIALIZATION_PROMPT
from knightagent.providers.base import ChatResponse, ProviderError, ToolCall
from knightagent.providers.ollama import OllamaProvider
from knightagent.tools.files import FileTools, Workspace, WriteApproval


class AutomationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = dict(format_attempts=3, max_steps=5, context_chars=24000,
                           tool_output_chars=6000, knowledge={"enabled": True, "max_chars": 6000})
        self.tools = FileTools(Workspace(self.root), WriteApproval(lambda _: "s", lambda _: None))
        self.logs = []

    def test_references_reach_planning_execution_and_review(self):
        provider = Mock(external=False)
        provider.chat.side_effect = [ChatResponse("PROJETO: criar script"),
            ChatResponse(calls=[ToolCall("create_file", {"path": "script.ts", "content": "function main(workbook: ExcelScript.Workbook) {}\n"})]),
            ChatResponse("Salvo"), ChatResponse("APROVADO")]
        library = Mock()
        library.search.return_value = "Fonte oficial: https://learn.microsoft.com/office/dev/scripts/ ; ExcelScript.Workbook"
        agent = Agent({"local": provider}, dict.fromkeys(("planner", "executor", "reviewer"), "local"),
                      self.tools, self.config, self.logs.append, knowledge=library)
        agent.run("Crie Office Script")
        library.search.assert_called_once()
        for call in provider.chat.call_args_list:
            self.assertIn("Fonte oficial", str(call.args[0]))
            self.assertIn("nunca instrucoes", str(call.args[0]))
        self.assertTrue((self.root / "script.ts").exists())

    def test_copilot_cannot_be_used_as_online_agent_provider(self):
        copilot = Mock(external=True, supports_tools=False)
        copilot.chat.return_value = ChatResponse("CHAT: Use Option Explicit.")
        agent = Agent({"copilot": copilot}, {"planner": "copilot"}, self.tools, self.config, self.logs.append)
        with self.assertRaisesRegex(ProviderError, "online estao bloqueados"):
            agent.run("Explique VBA")
        copilot.chat.assert_not_called()

    def test_reference_budget_and_library_cannot_be_disabled_by_legacy_flag(self):
        provider = Mock(external=False)
        provider.chat.return_value = ChatResponse("CHAT: resposta")
        library = Mock()
        library.search.return_value = "REFERENCIA " * 4000
        self.config.update(context_chars=8000, tool_output_chars=1000)
        agent = Agent({"local": provider}, {"planner": "local"}, self.tools, self.config,
                      self.logs.append, knowledge=library)
        agent.run("Explique Python")
        messages, definitions = provider.chat.call_args.args
        self.assertLessEqual(len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(definitions)), 8000)
        self.config["knowledge"]["enabled"] = False
        library.reset_mock()
        agent.run("Oi")
        library.search.assert_called_once()
        self.assertIn("REFERENCIA", str(provider.chat.call_args.args[0]))

    def test_library_error_does_not_block_chat(self):
        provider = Mock(external=False)
        provider.chat.return_value = ChatResponse("CHAT: Ola")
        library = Mock()
        library.search.side_effect = sqlite3.OperationalError("locked")
        agent = Agent({"local": provider}, {"planner": "local"}, self.tools, self.config,
                      self.logs.append, knowledge=library)
        self.assertEqual(agent.run("Oi"), "Ola")
        self.assertTrue(any("biblioteca local indisponivel" in item for item in self.logs))
        self.assertIn("Nao foram recuperadas referencias locais", str(provider.chat.call_args.args[0]))

    def test_escaped_code_references_fit_serialized_context(self):
        provider = Mock(external=False)
        provider.chat.return_value = ChatResponse("CHAT: ok")
        self.config["tool_output_chars"] = 1000
        agent = Agent({"local": provider}, {"planner": "local"}, self.tools, self.config, self.logs.append)
        agent.reference_context = '"' * 6000
        agent._phase("planner", "x" * 15600, "")
        messages, definitions = provider.chat.call_args.args
        self.assertLessEqual(len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(definitions)), 24000)

    def test_memory_remembers_office_scripts_and_vbnet(self):
        for filename in ("script.ts", "Program.vb"):
            with self.subTest(filename=filename):
                self.tools.changed.clear()
                self.tools.create_file(filename, "' codigo aprovado\n")
                memory = MemoryStore(self.root / (filename + ".sqlite3"))
                memory.remember("automacao planilhas", "aprovado", self.root, self.tools)
                self.assertEqual(memory.recall("automacao planilhas", self.root)[0]["arquivos"][0]["path"], filename)

    def test_default_config_and_strict_library_options(self):
        path = self.root / "config.yaml"
        path.write_text("ollama:\n  model: local\n", encoding="utf-8")
        self.assertEqual(load(path)["knowledge"], {"enabled": True, "max_chars": 6000})
        for value in ("  enabled: sim", "  max_chars: true", "  max_chars: 20000", "  url: https://evil.test/"):
            path.write_text("ollama:\n  model: local\nknowledge:\n" + value, encoding="utf-8")
            with self.subTest(value=value), self.assertRaises(ValueError):
                load(path)

    def test_model_creation_verifies_profile_without_training(self):
        config = {"ollama": {"model": "base:7b"}, "timeout": 30}
        with patch("knightagent.automation_model.OllamaProvider") as factory:
            provider = factory.return_value
            provider.url = "http://localhost:11434"
            provider.post.side_effect = [{"status": "success"}, {"system": SPECIALIZATION_PROMPT}]
            result = create_automation_model(config)
            self.assertFalse(result["weights_trained"])
            provider.test_connection.assert_called_once()
            self.assertEqual(provider.post.call_args_list[0].kwargs["json"]["from"], "base:7b")
            provider.close.assert_called_once()
        with self.assertRaises(ValueError):
            create_automation_model(config, name="base:7b")

    def test_model_creation_never_downloads_missing_or_remote_bases(self):
        config = {"ollama": {"model": "base:7b"}, "timeout": 30}
        for reason in ("Modelo ausente", "Modelo remoto/cloud bloqueado"):
            with self.subTest(reason=reason), patch("knightagent.automation_model.OllamaProvider") as factory:
                provider = factory.return_value
                provider.test_connection.side_effect = ProviderError(reason)
                with self.assertRaises(ProviderError):
                    create_automation_model(config)
                provider.post.assert_not_called()
                provider.close.assert_called_once()
        with patch("knightagent.automation_model.OllamaProvider") as factory:
            with self.assertRaises(ValueError):
                create_automation_model(config, base="model:cloud")
            factory.assert_not_called()

    def test_legacy_external_configuration_cannot_build_online_provider(self):
        config = {"ollama": {"model": "local"}, "timeout": 30,
                  "providers": {"openai": {"enabled": True, "model": "test"}}}
        with patch("knightagent.config.settings.credential", return_value="invalid key"), \
                patch("knightagent.config.settings.OllamaProvider") as factory:
            providers, roles = build_providers(config)
            self.assertEqual(set(providers), {"ollama"})
            self.assertEqual(set(roles.values()), {"ollama"})

    def test_ollama_connection_and_truncated_tool_response(self):
        def transport(request):
            if request.url.path.endswith("tags"):
                return httpx.Response(200, json={"models": [{"name": "local:latest"}]})
            if request.url.path.endswith("show"):
                return httpx.Response(200, json={"capabilities": ["tools"]})
            return httpx.Response(200, json={"done_reason": "length", "message": {"content": "partial"}})
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            provider = OllamaProvider("local", client=client)
            self.assertIn("instalado", provider.test_connection())
            with self.assertRaisesRegex(ProviderError, "limite de saida"):
                provider.chat([{"role": "user", "content": "crie"}], [])


if __name__ == "__main__":
    unittest.main()
