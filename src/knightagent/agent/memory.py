"""Exemplos aprovados, armazenados localmente em SQLite."""

import json
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import unicodedata


STOP = {"para", "como", "com", "uma", "um", "que", "dos", "das", "de", "do", "da", "por", "crie", "criar", "arquivo", "arquivos", "codigo", "programa"}


def terms(text):
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return {word for word in re.findall(r"[a-z0-9_]{3,}", plain) if word not in STOP}


class MemoryStore:
    def __init__(self, path, scope="global"):
        if scope not in {"global", "workspace"}:
            raise ValueError("Escopo da memoria invalido.")
        self.path = Path(path)
        self.scope = scope

    def _open(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("""CREATE TABLE IF NOT EXISTS examples (
            id INTEGER PRIMARY KEY,
            workspace TEXT NOT NULL,
            request TEXT NOT NULL,
            summary TEXT NOT NULL,
            files TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        return connection

    def clear(self):
        """Remove os exemplos locais sem alterar historico, configuracoes ou arquivos."""
        if not self.path.exists():
            return
        with closing(self._open()) as db:
            db.execute("PRAGMA secure_delete=ON")
            with db:
                db.execute("DELETE FROM examples")

    def remember(self, request, summary, workspace, tools):
        files = []
        for path in sorted(tools.changed)[:3]:
            if Path(path).suffix.lower() not in {".py", ".bas", ".cls", ".vb", ".ts"}:
                continue
            try:
                files.append({"path": path, "content": tools.review_snapshot(path, 3000)})
            except (OSError, ValueError, UnicodeError):
                continue
        if not files:
            return
        with closing(self._open()) as db:
            with db:
                db.execute("INSERT INTO examples (workspace, request, summary, files) VALUES (?, ?, ?, ?)",
                           (str(workspace), request[:3000], summary[:2000], json.dumps(files, ensure_ascii=False)))
                db.execute("DELETE FROM examples WHERE id NOT IN (SELECT id FROM examples ORDER BY id DESC LIMIT 500)")

    def recall(self, query, workspace, limit=3):
        query_terms = terms(query)
        if not query_terms:
            return []
        with closing(self._open()) as db:
            if self.scope == "workspace":
                rows = db.execute("SELECT request, summary, files FROM examples WHERE workspace=? ORDER BY id DESC LIMIT 300", (str(workspace),)).fetchall()
            else:
                rows = db.execute("SELECT request, summary, files FROM examples ORDER BY id DESC LIMIT 300").fetchall()
        ranked = []
        for request, summary, files in rows:
            score = len(query_terms & terms(request))
            if score:
                ranked.append((score, request, summary, files))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [{"pedido": request[:500], "resultado": summary[:500],
                 "arquivos": [{"path": item["path"], "content": item["content"][:1500]} for item in json.loads(files)[:2]]}
                for _, request, summary, files in ranked[:limit]]
