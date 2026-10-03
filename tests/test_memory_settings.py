import tempfile
from pathlib import Path
import unittest

import httpx

from knightagent.agent.memory import MemoryStore
from knightagent.agent.loop import Agent
from knightagent.config.performance import PROFILES, apply_profile
from knightagent.config.settings import load
from knightagent.gui.settings import installed_models
from knightagent.tools.files import FileTools, Workspace, WriteApproval
from knightagent.providers.base import ChatResponse, ToolCall
from unittest.mock import Mock


class MemorySettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_global_memory_recalls_approved_code_across_projects(self):
        first = self.root / "primeiro"
        second = self.root / "segundo"
        first.mkdir()
        second.mkdir()
        tools = FileTools(Workspace(first), WriteApproval(lambda _: "s", lambda _: None))
        tools.create_file("macro.bas", "Option Explicit\nSub CopiarColunas()\nEnd Sub\n")
        store = MemoryStore(self.root / "memory.sqlite3", "global")
        store.remember("Criar macro VBA para copiar colunas", "macro aprovada", first, tools)
        recalled = store.recall("Preciso de macro VBA que copie colunas", second)
        self.assertEqual(recalled[0]["arquivos"][0]["path"], "macro.bas")
        self.assertIn("CopiarColunas", recalled[0]["arquivos"][0]["content"])
        isolated = MemoryStore(self.root / "memory.sqlite3", "workspace")
        self.assertEqual(isolated.recall("macro VBA copiar colunas", second), [])

    def test_profile_values_and_yaml_validation(self):
        config = load("config.yaml")
        for level in PROFILES:
            applied = apply_profile(config, level)
            self.assertEqual(applied["ollama"]["num_ctx"], PROFILES[level]["num_ctx"])
            self.assertEqual(applied["ollama"]["num_predict"], PROFILES[level]["num_predict"])
        path = self.root / "bad.yaml"
        path.write_text("ollama:\n  model: x\nperformance:\n  level: maximo\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            load(path)

    def test_agent_records_and_reuses_approved_example(self):
        tools = FileTools(Workspace(self.root), WriteApproval(lambda _: "s", lambda _: None))
        store = MemoryStore(self.root / "memory.sqlite3")
        provider = Mock(external=False)
        provider.chat.side_effect = [
            ChatResponse("PROJETO: criar macro"),
            ChatResponse(calls=[ToolCall("create_file", {"path": "macro.bas", "content": "Option Explicit\nSub CopiarColunas()\nEnd Sub\n"})]),
            ChatResponse("macro salva"),
            ChatResponse("APROVADO"),
            ChatResponse("CHAT: Posso aproveitar a macro anterior."),
        ]
        config = dict(format_attempts=3, max_steps=5, context_chars=24000, tool_output_chars=6000)
        agent = Agent({"ollama": provider}, dict.fromkeys(("planner", "executor", "reviewer"), "ollama"), tools, config,
                      emit=lambda _: None, memory=store)
        agent.run("Crie macro VBA para copiar colunas")
        agent.run("Como adaptar minha macro VBA que copia colunas?")
        self.assertIn("CopiarColunas", str(provider.chat.call_args.args[0]))

    def test_model_inventory_and_parameter_size(self):
        def response(request):
            self.assertEqual(request.url.path, "/api/tags")
            self.assertEqual(request.url.host, "127.0.0.1")
            return httpx.Response(200, json={"models": [
                {"name": "qwen2.5:7b", "details": {"parameter_size": "7.6B"}},
                {"name": "gpt-oss:120b-cloud"},
                {"name": "remote-alias", "remote_host": "https://ollama.com"},
                {"name": "other-alias", "details": {"remote_model": "remote"}},
                {"name": "x:cloud"},
                None,
            ]})
        with httpx.Client(transport=httpx.MockTransport(response)) as client:
            self.assertEqual(installed_models("http://localhost:11434", client), {"qwen2.5:7b": "7.6B"})
            for url in ("https://example.com", "http://127.0.0.1@evil.example", "http://localhost:11434/proxy",
                        "http://localhost:11434?target=internet", "http://localhost:11434#remote"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    installed_models(url, client)
