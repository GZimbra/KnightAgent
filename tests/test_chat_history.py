import tempfile
import unittest
from pathlib import Path
from knightagent.gui.history import ChatHistory


class ChatHistoryTests(unittest.TestCase):
    def test_persistence_context_and_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'chats.sqlite3'
            history = ChatHistory(path)
            one = history.create(folder, 'Primeiro pedido')
            history.append(one, 'user', 'Crie o arquivo')
            history.append(one, 'approval', 'Pode escrever?')
            history.append(one, 'decision', 'Aprovar tudo')
            history.append(one, 'result', 'Arquivo criado')
            history.append(one, 'user', 'Pedido interrompido')
            two = history.create(folder, 'Outra conversa')
            history.append(two, 'user', 'Olá')
            history.append(two, 'result', 'Olá!')
            history.close()
            reopened = ChatHistory(path)
            self.assertEqual(reopened.dialog(one), [('usuario', 'Crie o arquivo'), ('assistente', 'Arquivo criado')])
            self.assertEqual(reopened.dialog(two), [('usuario', 'Olá'), ('assistente', 'Olá!')])
            self.assertEqual(len(reopened.messages(one)), 5)
            self.assertEqual(reopened.list()[0]['id'], two)
            reopened.clear()
            self.assertEqual(reopened.list(), [])
            self.assertEqual(reopened.messages(one), [])
            reopened.close()

    def test_context_is_bounded_to_completed_pairs(self):
        history = ChatHistory(':memory:')
        self.addCleanup(history.close)
        chat = history.create('.', 'Conversation')
        for i in range(7):
            history.append(chat, 'user', str(i))
            history.append(chat, 'result', str(i))
        self.assertEqual(len(history.dialog(chat)), 6)
        self.assertEqual(history.dialog(chat)[0], ('usuario', '4'))
