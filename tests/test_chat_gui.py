import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from knightagent.agent.loop import Agent
from knightagent.tools.files import FileTools, Workspace, WriteApproval


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = []
        self.tools = FileTools(Workspace(self.temp.name), WriteApproval(lambda _: "s", lambda _: None))
        self.config = dict(format_attempts=3, max_steps=5, context_chars=24000, tool_output_chars=6000)

    def test_greeting_answers_without_executor_or_reviewer(self):
        provider = Mock(external=False)
        from knightagent.providers.base import ChatResponse
        provider.chat.return_value = ChatResponse("CHAT: Olá! Como posso ajudar?")
        agent = Agent({"ollama": provider}, dict.fromkeys(("planner", "executor", "reviewer"), "ollama"), self.tools, self.config, self.output.append)
        self.assertEqual(agent.run("Oi"), "Olá! Como posso ajudar?")
        self.assertEqual(provider.chat.call_count, 1)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
        agent.run("E agora?")
        self.assertIn("Olá! Como posso ajudar?", str(provider.chat.call_args))

    def test_project_uses_full_workflow(self):
        from knightagent.providers.base import ChatResponse, ToolCall
        provider = Mock(external=False)
        provider.chat.side_effect = [
            ChatResponse("PROJETO: criar um script Python simples"),
            ChatResponse(calls=[ToolCall("create_file", {"path": "script.py", "content": "print('olá')\n"})]),
            ChatResponse("script salvo"),
            ChatResponse("APROVADO"),
        ]
        agent = Agent({"ollama": provider}, dict.fromkeys(("planner", "executor", "reviewer"), "ollama"), self.tools, self.config, self.output.append)
        self.assertEqual(agent.run("Crie um script Python"), "script salvo")
        self.assertEqual((Path(self.temp.name) / "script.py").read_text(encoding="utf-8"), "print('olá')\n")

    def test_gui_import_without_starting_window(self):
        from knightagent.gui.main import DesktopApp, main
        self.assertTrue(callable(main))
        self.assertTrue(callable(DesktopApp._answer_approval))
