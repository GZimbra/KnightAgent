"""Read-only graph projection of the three local KnightAgent databases."""

from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sqlite3


TOOL_EVENT = re.compile(r"^\[(planner|executor|reviewer)\] ([a-z][a-z0-9_]*)$")


@dataclass
class GraphSnapshot:
    nodes: dict = field(default_factory=dict)
    edges: set = field(default_factory=set)
    neighbors: dict = field(default_factory=lambda: defaultdict(set))

    def node(self, key, label, kind, detail="", **meta):
        self.nodes[key] = {"label": str(label), "kind": kind, "detail": str(detail), **meta}

    def edge(self, a, b):
        if a == b or a not in self.nodes or b not in self.nodes:
            return
        self.edges.add(tuple(sorted((a, b))))
        self.neighbors[a].add(b)
        self.neighbors[b].add(a)


def _connect(path):
    if not path.is_file():
        return None
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)


def _has_table(db, table):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def load_graph(directory):
    """Load every stored record; the view pages large neighborhoods on demand."""
    directory = Path(directory).resolve()
    graph = GraphSnapshot()
    pending_links = []
    graph.node("root", "KnightAgent", "root", "Bases SQLite locais do KnightAgent")
    for key, label, filename in (
        ("chats", "Conversas", "knightagent-chats.sqlite3"),
        ("knowledge", "Conhecimento", "knightagent-knowledge.sqlite3"),
        ("memory", "Aprendizados", "knightagent-memory.sqlite3"),
    ):
        graph.node(key, label, "database", str(directory / filename))
        graph.edge("root", key)

    db = _connect(directory / "knightagent-chats.sqlite3")
    if db is not None:
        try:
            chats = db.execute("SELECT id, title, workspace, updated FROM chats ORDER BY id")
            for chat_id, title, workspace, updated in chats:
                key = f"chat:{chat_id}"
                graph.node(key, title, "chat", f"Conversa #{chat_id}\nProjeto: {workspace}\nAtualizada: {updated}")
                graph.edge("chats", key)
                workspace_key = f"workspace:{workspace}"
                if workspace_key not in graph.nodes:
                    graph.node(workspace_key, Path(workspace).name or workspace, "workspace", workspace)
                    graph.edge("root", workspace_key)
                graph.edge(key, workspace_key)
            messages = db.execute("SELECT id, chat_id, kind, content FROM messages ORDER BY id")
            for message_id, chat_id, kind, content in messages:
                parent = f"chat:{chat_id}"
                if parent not in graph.nodes:
                    continue
                key = f"message:{message_id}"
                label = {"user": "Pedido", "result": "Resposta", "event": "Evento", "diff": "Alteração",
                         "error": "Erro", "end": "Fim", "decision": "Decisão", "approval": "Aprovação"}.get(kind, kind)
                graph.node(key, f"{label} #{message_id}", "message", content, message_kind=kind)
                graph.edge(parent, key)
                match = TOOL_EVENT.fullmatch(content) if kind == "event" else None
                if match:
                    tool_key = f"tool:{match[2]}"
                    if tool_key not in graph.nodes:
                        graph.node(tool_key, match[2], "tool", "Ferramenta registrada no histórico de execução")
                        graph.edge("root", tool_key)
                    graph.edge(key, tool_key)
            if _has_table(db, "usage_links"):
                for message_id, source_kind, source_id in db.execute(
                    "SELECT request_message_id, source_kind, source_id FROM usage_links"):
                    target = f"doc:{source_id}" if source_kind == "document" else f"example:{source_id}"
                    if source_kind == "learned" and f"message:{message_id}" in graph.nodes:
                        graph.nodes[f"message:{message_id}"]["detail"] += "\n\nNovo exemplo aprovado registrado na memória."
                    # Resolve after the other databases are loaded.
                    pending_links.append((f"message:{message_id}", target))
        finally:
            db.close()

    db = _connect(directory / "knightagent-knowledge.sqlite3")
    if db is not None:
        try:
            for doc_id, family, title, url, origin, digest, updated in db.execute(
                "SELECT id, family, title, url, origin, digest, updated_at FROM documents ORDER BY family, title"):
                family_key = f"family:{family}"
                if family_key not in graph.nodes:
                    graph.node(family_key, family, "family", f"Área de conhecimento: {family}")
                    graph.edge("knowledge", family_key)
                key = f"doc:{doc_id}"
                graph.node(key, title, "document", f"Origem: {origin}\nFamília: {family}\nFonte: {url}\nSHA-256: {digest}\nAtualizado: {updated}",
                           new=origin == "local")
                graph.edge(family_key, key)
            if _has_table(db, "sync_runs"):
                for family, report in db.execute("SELECT family, report FROM sync_runs ORDER BY family"):
                    key = f"sync:{family}"
                    graph.node(key, f"Sincronização: {family}", "sync", report)
                    graph.edge("knowledge", key)
                    graph.edge(key, f"family:{family}")
            for rowid, doc_id, title, content in db.execute("SELECT rowid, document_id, title, text FROM chunks ORDER BY rowid"):
                parent = f"doc:{doc_id}"
                if parent not in graph.nodes:
                    continue
                key = f"chunk:{rowid}"
                graph.node(key, f"Trecho #{rowid}", "chunk", content)
                graph.edge(parent, key)
        finally:
            db.close()

    db = _connect(directory / "knightagent-memory.sqlite3")
    if db is not None:
        try:
            for example_id, workspace, request, summary, files, created in db.execute(
                "SELECT id, workspace, request, summary, files, created_at FROM examples ORDER BY id"):
                key = f"example:{example_id}"
                graph.node(key, f"Exemplo #{example_id}", "example",
                           f"Pedido: {request}\n\nResultado aprovado: {summary}\n\nCriado: {created}", new=True)
                graph.edge("memory", key)
                workspace_key = f"workspace:{workspace}"
                if workspace_key not in graph.nodes:
                    graph.node(workspace_key, Path(workspace).name or workspace, "workspace", workspace)
                    graph.edge("root", workspace_key)
                graph.edge(key, workspace_key)
                try:
                    file_rows = json.loads(files)
                except (TypeError, ValueError):
                    file_rows = []
                for file in file_rows:
                    if not isinstance(file, dict) or not isinstance(file.get("path"), str):
                        continue
                    file_key = f"file:{example_id}:{file['path']}"
                    if file_key not in graph.nodes:
                        graph.node(file_key, Path(file["path"]).name, "file",
                                   f"Arquivo: {file['path']}\n\n{file.get('content', '')}")
                    graph.edge(key, file_key)
        finally:
            db.close()

    for source, target in pending_links:
        graph.edge(source, target)
    return graph
