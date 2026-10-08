from copy import deepcopy
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from knightagent.gui.main import DesktopApp
from knightagent.providers.base import ChatResponse
from knightagent.tools.files import Workspace


class ChatDesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "config.yaml"
        self.path.write_text("ollama:\n  model: test\nmemory:\n  enabled: false\n", encoding="utf-8")
        self.root = tk.Tk()
        self.root.withdraw()
        starter = patch("knightagent.gui.main.DesktopApp._start_runtime")
        starter.start()
        self.addCleanup(starter.stop)
        runtime = patch("knightagent.gui.main.OllamaRuntime")
        runtime.start()
        self.addCleanup(runtime.stop)
        self.copilot_clients = []

        def create_client(*args):
            client = Mock()
            client.consult.return_value = "Recomendação complementar: valide os dados de entrada."
            self.copilot_clients.append(client)
            return client

        client_factory = patch("knightagent.gui.main.CopilotClient", side_effect=create_client)
        self.copilot_factory = client_factory.start()
        self.addCleanup(client_factory.stop)
        self.app = DesktopApp(self.root, self.path)
        self.app.runtime_ready = True
        self.app.workspace.set(self.temp.name)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.app.busy = False
        self.app._close()
        self.temp.cleanup()

    def drain(self):
        self.root.after_cancel(self.app.drain_timer)
        self.app._drain()
        self.root.update_idletasks()

    def send_without_thread(self, text):
        self.app.input.insert("1.0", text)
        with patch("knightagent.gui.main.Thread"):
            self.app._send()

    def test_real_agent_chat_result_history_and_context_restore(self):
        self.send_without_thread("Olá")
        chat_id = self.app.chat_id
        self.assertTrue(self.app.busy)
        self.assertIsNotNone(self.app.orb.timer)
        provider = Mock(external=False)
        provider.chat.return_value = ChatResponse("CHAT: Olá! Como posso ajudar?")
        with patch("knightagent.gui.main.build_providers", return_value=(
                {"ollama": provider}, dict.fromkeys(("planner", "executor", "reviewer"), "ollama"))):
            self.app._run("Olá", Workspace(self.temp.name))
        self.drain()
        self.assertFalse(self.app.busy)
        self.assertIsNone(self.app.orb.timer)
        # Final text is not rendered twice despite the agent's emitted copy.
        replies = [node for node in self.app.flow.nodes if node[1] == "Olá! Como posso ajudar?"]
        self.assertEqual(len(replies), 1)
        self.app._new_chat()
        self.assertIsNone(self.app.agent)
        self.assertEqual(self.app.restored_dialog, [])
        self.app.chat_list.selection_set(0)
        self.app._open_chat()
        self.assertEqual(self.app.chat_id, chat_id)
        self.assertEqual(self.app.restored_dialog, [("usuario", "Olá"), ("assistente", "Olá! Como posso ajudar?")])

    def test_approval_and_busy_navigation_are_isolated(self):
        self.send_without_thread("Crie um arquivo")
        chat_id = self.app.chat_id
        self.app._new_chat()
        self.assertEqual(self.app.chat_id, chat_id)
        gate, answer = Event(), {}
        self.app.events.put(("diff", "--- antigo\n+++ novo\n+conteúdo"))
        self.app.events.put(("approval", ("Gravar?", gate, answer)))
        self.drain()
        self.assertIsNone(self.app.orb.timer)
        self.assertEqual(self.app.approval_bar.winfo_manager(), "pack")
        self.app._answer_approval("n")
        self.assertTrue(gate.is_set())
        self.assertEqual(answer["value"], "n")
        self.assertIsNotNone(self.app.orb.timer)
        self.app.events.put(("done", None))
        self.drain()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.history.messages(chat_id)[-2]["kind"], "decision")
        self.assertIn("Alterações recusadas: 1.", self.app.flow.summary_text.get("1.0", "end"))

    def test_saved_copilot_client_reaches_agent_and_local_model_only_when_enabled(self):
        initial_client = self.app.copilot_client
        saved = deepcopy(self.app.config)
        saved["complementary"].update(copilot=True, mode="account",
                                       client_id="12345678-1234-1234-1234-123456789abc")
        self.app._settings_saved(saved, self.path)
        initial_client.close.assert_called_once_with()
        active_client = self.app.copilot_client
        self.assertIsNot(active_client, initial_client)
        self.copilot_factory.assert_called_with(self.path, saved["complementary"])
        active_client.login.assert_not_called()

        provider = Mock(external=False)
        provider.chat.return_value = ChatResponse("CHAT: Valide os dados antes de processar.")
        roles = dict.fromkeys(("planner", "executor", "reviewer"), "ollama")
        self.send_without_thread("Como evitar entradas inválidas?")
        with patch("knightagent.gui.main.build_providers", return_value=({"ollama": provider}, roles)):
            self.app._run("Como evitar entradas inválidas?", Workspace(self.temp.name))
        self.drain()
        self.assertIs(self.app.agent.complementary, active_client)
        active_client.consult.assert_called_once()
        self.assertIn("Como evitar entradas inválidas?", active_client.consult.call_args.args[0])
        messages = provider.chat.call_args.args[0]
        self.assertTrue(any("Recomendação complementar" in message["content"] for message in messages))
        self.assertFalse(self.app.busy)
        self.assertTrue(any(row["kind"] == "result" and "Valide os dados" in row["content"]
                            for row in self.app.history.messages(self.app.chat_id)))

        disabled = deepcopy(saved)
        disabled["complementary"]["copilot"] = False
        self.app._settings_saved(disabled, self.path)
        active_client.close.assert_called_once_with()
        self.send_without_thread("Continuar localmente")
        with patch("knightagent.gui.main.build_providers", return_value=({"ollama": provider}, roles)):
            self.app._run("Continuar localmente", Workspace(self.temp.name))
        self.drain()
        self.app.copilot_client.consult.assert_not_called()

    def test_worker_error_unlocks_input_and_is_persisted(self):
        self.send_without_thread("Olá")
        with patch("knightagent.gui.main.build_providers", side_effect=ValueError("Modelo indisponível")):
            self.app._run("Olá", Workspace(self.temp.name))
        self.drain()
        self.assertEqual(str(self.app.input.cget("state")), "normal")
        self.assertTrue(any(row["kind"] == "error" for row in self.app.history.messages(self.app.chat_id)))
        self.assertEqual(self.app.flow.graph.winfo_manager(), "")
        self.assertIn("Modelo indisponível", self.app.flow.summary_text.get("1.0", "end"))

    def test_interrupted_chat_never_reactivates_approval(self):
        chat_id = self.app.history.create(self.temp.name, "Interrompida")
        self.app.history.append(chat_id, "user", "Pedido")
        self.app.history.append(chat_id, "approval", "Gravar arquivo?")
        self.app._refresh_history()
        self.app.chat_list.selection_set(0)
        self.app._open_chat()
        self.assertIsNone(self.app.approval)
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.restored_dialog, [])
        self.assertEqual(self.app.flow.nodes[-1][0], "error")
        self.assertEqual(self.app.flow.graph.winfo_manager(), "")
        self.assertIn("Esta execução foi interrompida", self.app.flow.summary_text.get("1.0", "end"))

    def test_execution_steps_collapse_into_summary_and_restore_collapsed(self):
        self.send_without_thread("Crie um arquivo")
        chat_id = self.app.chat_id
        self.app.events.put(("event", "Planejando..."))
        self.app.events.put(("event", "[planner] read_file"))
        self.app.events.put(("event", "[executor] SALVO: src/exemplo.py"))
        self.drain()
        self.assertEqual(self.app.flow.graph.winfo_manager(), "pack")
        self.assertIsNone(self.app.flow.summary_panel)

        self.app.events.put(("event", "APROVADO"))
        self.app.events.put(("result", "Arquivo criado e revisado."))
        self.app.events.put(("done", None))
        self.drain()
        flow = self.app.flow
        self.assertEqual(flow.graph.winfo_manager(), "")
        summary = flow.summary_text.get("1.0", "end")
        self.assertIn("src/exemplo.py", summary)
        self.assertIn("Arquivo criado e revisado.", summary)
        self.assertIn("Revisão do agente: aprovada", summary)
        flow.details_button.invoke()
        self.assertEqual(flow.graph.winfo_manager(), "pack")
        flow.details_button.invoke()
        self.assertEqual(flow.graph.winfo_manager(), "")

        self.app._new_chat()
        self.app.chat_list.selection_set(0)
        self.app._open_chat()
        self.assertEqual(self.app.chat_id, chat_id)
        self.assertEqual(self.app.flow.graph.winfo_manager(), "")
        self.assertIn("src/exemplo.py", self.app.flow.summary_text.get("1.0", "end"))

    def test_compact_layout_keeps_composer_and_flow_visible(self):
        self.root.geometry("900x680")
        self.root.deiconify()
        self.app.chat_id = self.app.history.create(self.temp.name, "Layout")
        self.app._record("user", "Mensagem de teste")
        self.app._record("event", "Planejando...")
        self.app._record("result", "Resposta breve")
        self.root.update()
        self.assertGreater(self.app.feed.winfo_height(), 120)
        self.assertGreater(self.app.input.winfo_width(), 250)
        for _, _, node in self.app.flow.nodes:
            self.assertLess(node.winfo_height(), 150)
        self.assertLess(self.app.input.winfo_rooty() + self.app.input.winfo_height(),
                        self.root.winfo_rooty() + self.root.winfo_height())

    def test_split_layout_keeps_sidebar_chat_and_dividers_aligned(self):
        self.root.geometry("900x680")
        self.root.deiconify()
        self.root.update()
        self.assertEqual(self.app.vertical_divider.winfo_width(), 1)
        self.assertEqual(self.app.vertical_divider.winfo_rootx(),
                         self.app.sidebar.winfo_rootx() + self.app.sidebar.winfo_width())
        self.assertEqual(self.app.main.winfo_rootx(), self.app.vertical_divider.winfo_rootx() + 1)
        self.assertEqual(self.app.header_divider.winfo_width(), self.app.main.winfo_width())
        self.assertGreater(self.app.feed.winfo_height(), 180)
        self.assertLess(self.app.composer_divider.winfo_rooty(), self.app.composer_panel.winfo_rooty())
        self.assertEqual(self.app.empty.winfo_manager(), "place")
        self.app._render("user", "Mensagem")
        self.assertFalse(self.app.empty.winfo_exists())
        self.app._new_chat()
        self.assertEqual(self.app.empty.winfo_manager(), "place")

    def test_history_refresh_keeps_scrolled_conversation_in_view(self):
        for index in range(35):
            self.app.history.create(self.temp.name, f"Conversa {index}")
        self.root.deiconify()
        self.app._refresh_history()
        self.root.update_idletasks()
        self.app.chat_list.yview_scroll(10 * self.app.chat_list.row_height, "units")
        self.root.update_idletasks()
        before = self.app.chat_list.canvasy(0)
        self.assertGreater(before, self.app.chat_list.inset)
        self.app.history.create(self.temp.name, "Conversa nova")
        self.app._refresh_history()
        self.root.update_idletasks()
        self.assertAlmostEqual(self.app.chat_list.canvasy(0) - before,
                               self.app.chat_list.row_height, delta=2)

    def test_wheel_exits_long_message_at_its_edge(self):
        from types import SimpleNamespace

        self.root.deiconify()
        self.app._render("user", "Linha longa de texto.\n" * 100)
        self.app._render("result", "Resposta longa.\n" * 100)
        self.root.update_idletasks()
        text = self.app.flow.nodes[0][2].text
        self.assertLess(text.yview()[1], 1)
        self.assertIsNone(text._wheel(SimpleNamespace(delta=-120)))
        text.yview_moveto(1)
        self.app.feed.canvas.yview_moveto(0)
        before = self.app.feed.canvas.yview()[0]
        self.assertEqual(text._wheel(SimpleNamespace(delta=-120)), "break")
        self.assertGreater(self.app.feed.canvas.yview()[0], before)

    def test_flow_arrows_grow_sequentially_and_survive_resize(self):
        from knightagent.gui.chat_widgets import FlowCard
        self.root.deiconify()
        flow = FlowCard(self.app.feed.body)
        with patch("knightagent.gui.chat_widgets.monotonic", return_value=100):
            flow.add("event", "Planejando...")
            flow.add("event", "Executando...")
            flow.add("event", "Revisando...")
            self.root.update_idletasks()
        self.assertEqual(flow.links[0]["progress"], 0)
        self.assertGreater(flow.links[1]["start"], flow.links[0]["start"])
        with patch("knightagent.gui.chat_widgets.monotonic", return_value=100.24):
            flow._draw_links()
        first = flow.links[0]
        self.assertAlmostEqual(first["progress"], .5)
        self.assertEqual(flow.links[1]["progress"], 0)
        coords = flow.rail.coords(first["line"])
        self.assertGreater(coords[3], coords[1])
        self.assertLess(coords[3], flow.nodes[1][2].winfo_y()+14)
        self.root.geometry("950x700")
        self.root.update_idletasks()
        with patch("knightagent.gui.chat_widgets.monotonic", return_value=102):
            flow._draw_links()
        self.assertTrue(all(link["progress"] == 1 for link in flow.links))
        self.assertAlmostEqual(flow.rail.coords(first["line"])[3], flow.nodes[1][2].winfo_y()+14)
        timer = flow.timer
        flow.destroy()
        self.assertNotIn(timer, self.root.tk.call("after", "info"))

    def test_historical_flow_does_not_replay_animations(self):
        self.app._render("user", "Pergunta antiga")
        self.app._render("event", "Planejando...")
        self.app._render("result", "Resposta antiga")
        self.assertEqual(self.app.flow.links[0]["progress"], 1)
        self.assertIsNone(self.app.flow.timer)
        self.assertFalse(self.app.flow.running)

    def test_selection_and_thinking_effects_stop_cleanly(self):
        self.app._render("user", "Pedido")
        self.app._render("event", "Planejando...")
        self.app._render("event", "Executando...")
        flow = self.app.flow
        first, second = (node[2] for node in flow.nodes)
        flow.select_node(first)
        self.assertTrue(first.panel.selected)
        flow.select_node(second)
        self.assertFalse(first.panel.selected)
        self.assertTrue(second.panel.selected)
        self.app._visual_state("Processando", active=True)
        self.assertTrue(flow.running)
        self.assertTrue(self.app.orb.active)
        self.assertTrue(all(self.app.orb.itemcget(item, "state") == "normal" for item in self.app.orb.orbits))
        self.app._visual_state("Aguardando aprovação")
        self.assertFalse(flow.running)
        self.assertFalse(self.app.orb.active)
        self.assertIsNone(self.app.orb.timer)
        self.assertTrue(all(self.app.orb.itemcget(item, "state") == "hidden" for item in self.app.orb.orbits))
        timers = [node[2].panel.effect_timer for node in flow.nodes]
        flow.destroy()
        pending = self.root.tk.call("after", "info")
        self.assertTrue(all(timer not in pending for timer in timers if timer))
