import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from knightagent.gui.graph_data import load_graph
from knightagent.gui.history import ChatHistory


class GraphDataTests(unittest.TestCase):
    def test_graph_connects_audited_sources_tools_and_new_learning(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            history = ChatHistory(directory / "knightagent-chats.sqlite3")
            chat = history.create(folder, "Criar script")
            request = history.append(chat, "user", "Crie um script")
            history.append(chat, "event", "[executor] create_file")
            history.record_usage(request, ["doc-1"], [], 7)
            history.close()
            with closing(sqlite3.connect(directory / "knightagent-knowledge.sqlite3")) as db, db:
                db.execute("CREATE TABLE documents (id TEXT, family TEXT, title TEXT, url TEXT, origin TEXT, digest TEXT, updated_at TEXT)")
                db.execute("CREATE TABLE chunks (document_id TEXT, title TEXT, text TEXT)")
                db.execute("INSERT INTO documents VALUES ('doc-1', 'python', 'Guia Python', 'local', 'local', 'digest', 'hoje')")
                db.execute("INSERT INTO chunks VALUES ('doc-1', 'Guia Python', 'Conteúdo do guia')")
            with closing(sqlite3.connect(directory / "knightagent-memory.sqlite3")) as db, db:
                db.execute("CREATE TABLE examples (id INTEGER, workspace TEXT, request TEXT, summary TEXT, files TEXT, created_at TEXT)")
                db.execute("INSERT INTO examples VALUES (7, ?, 'Crie um script', 'Aprovado', '[]', 'hoje')", (folder,))
            graph = load_graph(directory)
            self.assertIn("doc:doc-1", graph.neighbors[f"message:{request}"])
            self.assertIn("example:7", graph.neighbors[f"message:{request}"])
            self.assertIn("tool:create_file", graph.nodes)
            self.assertEqual(sum(node["kind"] == "chunk" for node in graph.nodes.values()), 1)
            self.assertTrue(graph.nodes["example:7"]["new"])
            self.assertIn("Novo exemplo", graph.nodes[f"message:{request}"]["detail"])

    def test_missing_databases_are_visible_without_creating_files(self):
        with tempfile.TemporaryDirectory() as folder:
            graph = load_graph(folder)
            self.assertEqual(set(graph.nodes), {"root", "chats", "knowledge", "memory"})
            self.assertEqual(len(list(Path(folder).iterdir())), 0)
