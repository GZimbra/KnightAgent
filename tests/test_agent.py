from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from knightagent.agent.loop import Agent
from knightagent.agent.parsing import FormatError
from knightagent.config.settings import load, build_providers
from knightagent.providers.base import ChatResponse, ToolCall, ProviderError
from knightagent.tools.files import Workspace, FileTools, WriteApproval


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tools = FileTools(Workspace(self.temp.name), WriteApproval(lambda _: "s", lambda _: None))
        self.config = dict(format_attempts=3, max_steps=5, context_chars=24000, tool_output_chars=6000)
        self.logs = []

    def test_end_to_end_vba_local_roles_and_review(self):
        planner = Mock(external=False)
        executor = Mock(external=False)
        reviewer = Mock(external=False)
        planner.chat.return_value = ChatResponse("Criar modulo VBA")
        executor.chat.side_effect = [ChatResponse(calls=[ToolCall("create_file", {"path": "Auto.bas", "content": "Option Explicit\n' ação\n"})]), ChatResponse("Arquivo salvo")]
        reviewer.chat.return_value = ChatResponse("APROVADO\nCodigo inspecionado")
        agent = Agent({"p": planner, "e": executor, "r": reviewer}, {"planner": "p", "executor": "e", "reviewer": "r"}, self.tools, self.config, self.logs.append)
        agent.run("Criar VBA")
        self.assertEqual(Path(self.temp.name, "Auto.bas").read_bytes(), "Option Explicit\r\n' ação\r\n".encode("cp1252"))
        self.assertFalse(any("provedor externo" in x for x in self.logs))
        self.assertEqual(reviewer.chat.call_count, 1)
        self.assertEqual(reviewer.chat.call_args.args[1], [])
        self.assertIn("Option Explicit", str(reviewer.chat.call_args.args[0]))

    def test_reviewer_cannot_repeat_file_reads(self):
        planner, executor, reviewer = Mock(external=False), Mock(external=False), Mock(external=False)
        planner.chat.return_value = ChatResponse("PROJETO: criar arquivo")
        executor.chat.side_effect = [ChatResponse(calls=[ToolCall("create_file", {"path": "macro.bas", "content": "Option Explicit\nSub X()\nEnd Sub\n"})]), ChatResponse("salvo")]
        reviewer.chat.side_effect = [ChatResponse(calls=[ToolCall("read_file", {"path": "macro.bas"})]), ChatResponse("APROVADO")]
        agent = Agent({"p": planner, "e": executor, "r": reviewer}, {"planner": "p", "executor": "e", "reviewer": "r"}, self.tools, self.config, self.logs.append)
        agent.run("Crie macro")
        self.assertEqual(reviewer.chat.call_count, 2)
        self.assertEqual(reviewer.chat.call_args.args[1], [])
        self.assertIn("Ferramenta desconhecida", str(reviewer.chat.call_args.args[0]))

    def test_invalid_review_verdict_does_not_restart_executor(self):
        planner, executor, reviewer = Mock(external=False), Mock(external=False), Mock(external=False)
        planner.chat.return_value = ChatResponse("PROJETO: arquivo")
        executor.chat.side_effect = [ChatResponse(calls=[ToolCall("create_file", {"path": "x.py", "content": "print(1)\n"})]), ChatResponse("feito")]
        reviewer.chat.return_value = ChatResponse("Vou pensar mais um pouco")
        agent = Agent({"p": planner, "e": executor, "r": reviewer}, {"planner": "p", "executor": "e", "reviewer": "r"}, self.tools, self.config, self.logs.append)
        with self.assertRaisesRegex(ProviderError, "revisao encerrada"):
            agent.run("Crie arquivo")
        self.assertEqual(executor.chat.call_count, 2)
        self.assertEqual(reviewer.chat.call_count, self.config["format_attempts"])

    def test_executor_must_save_before_review(self):
        planner, executor, reviewer = Mock(external=False), Mock(external=False), Mock(external=False)
        planner.chat.return_value = ChatResponse("PROJETO: criar arquivo")
        executor.chat.side_effect = [ChatResponse("Vou criar o arquivo"),
                                     ChatResponse(calls=[ToolCall("create_file", {"path": "feito.py", "content": "print(1)\n"})]),
                                     ChatResponse("salvo")]
        reviewer.chat.return_value = ChatResponse("APROVADO")
        agent = Agent({"p": planner, "e": executor, "r": reviewer}, {"planner": "p", "executor": "e", "reviewer": "r"}, self.tools, self.config, self.logs.append)
        agent.run("Crie feito.py")
        self.assertEqual(reviewer.chat.call_count, 1)
        self.assertTrue(Path(self.temp.name, "feito.py").exists())
        self.assertIn("Nenhum arquivo foi salvo", " ".join(self.logs))

    def test_executor_never_saves_cannot_be_approved(self):
        planner, executor, reviewer = Mock(external=False), Mock(external=False), Mock(external=False)
        planner.chat.return_value = ChatResponse("PROJETO: criar arquivo")
        executor.chat.return_value = ChatResponse("Pronto, criei o arquivo")
        agent = Agent({"p": planner, "e": executor, "r": reviewer}, {"planner": "p", "executor": "e", "reviewer": "r"}, self.tools, self.config, self.logs.append)
        with self.assertRaisesRegex(ProviderError, "sem salvar arquivo"):
            agent.run("Crie feito.py")
        reviewer.chat.assert_not_called()
        self.assertEqual(executor.chat.call_count, 3)

    def test_format_retries_and_limit(self):
        provider = Mock(external=False)
        provider.chat.side_effect = [FormatError("JSON invalido"), ChatResponse("ok")]
        agent = Agent({"local": provider}, {"executor": "local"}, self.tools, self.config, self.logs.append)
        self.assertEqual(agent._chat("executor", [{"role": "user", "content": "x"}], []).content, "ok")
        self.assertIn("Erro de formato", str(provider.chat.call_args))
        provider.chat.side_effect = FormatError("JSON invalido")
        with self.assertRaisesRegex(ProviderError, "Limite de tentativas"):
            agent._chat("executor", [], [])

    def test_empty_reviewer_response_retries(self):
        provider = Mock(external=False)
        provider.chat.side_effect = [ChatResponse(""), ChatResponse("APROVADO")]
        agent = Agent({"local": provider}, {"reviewer": "local"}, self.tools, self.config, self.logs.append)
        self.assertEqual(agent._chat("reviewer", [{"role": "user", "content": "revise"}], []).content, "APROVADO")
        self.assertEqual(provider.chat.call_count, 2)
        self.assertIn("Resposta vazia", str(provider.chat.call_args))

    def test_provider_error_no_fallback(self):
        local, external = Mock(external=False), Mock(external=True)
        local.chat.side_effect = ProviderError("timeout")
        agent = Agent({"local": local, "external": external}, {"executor": "local"}, self.tools, self.config)
        with self.assertRaises(ProviderError):
            agent._chat("executor", [], [])
        external.chat.assert_not_called()

    def test_no_external_with_environment_key_only(self):
        config = load("config.example.toml")
        with patch("knightagent.config.settings.credential") as secret:
            providers, roles = build_providers(config)
        self.addCleanup(providers["ollama"].close)
        secret.assert_not_called()
        self.assertEqual(set(roles.values()), {"ollama"})

    def test_legacy_external_plaintext_key_is_discarded(self):
        config = Path(self.temp.name, "config.toml")
        config.write_text('[ollama]\nmodel="x"\n[providers.openai]\nenabled=true\nmodel="x"\napi_key="do-not-log"\n')
        loaded = load(config)
        self.assertNotIn("providers", loaded)
        self.assertNotIn("do-not-log", str(loaded))

    def test_yaml_configuration_and_invalid_keys(self):
        path = Path(self.temp.name, "config.yaml")
        path.write_text("workspace: .\nollama:\n  model: qwen2.5:7b\nroles:\n  executor: ollama\n", encoding="utf-8")
        parsed = load(path)
        self.assertEqual(parsed["ollama"]["model"], "qwen2.5:7b")
        self.assertEqual(parsed["workspace"], self.temp.name)
        for content in (
            "ollama:\n  model: x\n  model: y\n",
            "ollama:\n  model: x\n  api_key: segredo\n",
            "!!python/object/apply:os.system ['exit 1']",
        ):
            path.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(ValueError):
                load(path)

    def test_context_limit_and_history_warning(self):
        agent = Agent({}, {}, self.tools, self.config, self.logs.append)
        history = [{"role": "system", "content": "system"}, {"role": "user", "content": "pedido"}] + [{"role": "user", "content": "x" * 6000} for _ in range(5)]
        agent._fit(history, [])
        self.assertEqual(history[1]["content"], "pedido")
        self.assertTrue(any("historico antigo" in line for line in self.logs))
        with self.assertRaises(ProviderError):
            agent._fit([{"role": "user", "content": "x" * 30000}], [])

    def test_reviewer_corrections_return_to_executor(self):
        provider = Mock(external=False)
        provider.chat.side_effect = [
            ChatResponse("plano"),
            ChatResponse(calls=[ToolCall("create_file", {"path": "modulo.py", "content": "print(1)\n"})]),
            ChatResponse("primeira versao"),
            ChatResponse("CORRIGIR\nAjuste o modulo"),
            ChatResponse(calls=[ToolCall("edit_file", {"path": "modulo.py", "old": "print(1)", "new": "print(2)"})]),
            ChatResponse("corrigido"),
            ChatResponse("APROVADO"),
        ]
        agent = Agent({"local": provider}, dict.fromkeys(("planner", "executor", "reviewer"), "local"), self.tools, self.config, self.logs.append)
        agent.run("pedido")
        self.assertEqual(provider.chat.call_count, 7)
        self.assertIn("Ajuste o modulo", str(provider.chat.call_args_list[4]))
