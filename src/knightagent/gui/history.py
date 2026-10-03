"""Local chat archive, independent of approved-code agent memory."""

import sqlite3
from datetime import datetime, timezone


class ChatHistory:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                workspace TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id),
                kind TEXT NOT NULL, content TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS messages_chat ON messages(chat_id, id);
        """)

    def create(self, workspace, title):
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO chats(title, workspace, updated) VALUES (?, ?, ?)",
                (title[:70], str(workspace), datetime.now(timezone.utc).isoformat()))
        return cursor.lastrowid

    def list(self):
        return self.db.execute("SELECT * FROM chats ORDER BY updated DESC, id DESC").fetchall()

    def messages(self, chat_id):
        return self.db.execute("SELECT kind, content FROM messages WHERE chat_id=? ORDER BY id", (chat_id,)).fetchall()

    def append(self, chat_id, kind, content):
        with self.db:
            self.db.execute("INSERT INTO messages(chat_id, kind, content) VALUES (?, ?, ?)",
                            (chat_id, kind, content))
            self.db.execute("UPDATE chats SET updated=? WHERE id=?",
                            (datetime.now(timezone.utc).isoformat(), chat_id))

    def dialog(self, chat_id):
        # Only completed user/result pairs become model context. Events, diffs,
        # interrupted requests and approval grants never become instructions.
        dialog, request = [], None
        for message in self.messages(chat_id):
            if message["kind"] == "user":
                request = message["content"]
            elif message["kind"] == "result" and request is not None:
                dialog.extend([("usuario", request), ("assistente", message["content"])])
                request = None
        return dialog[-6:]

    def close(self):
        self.db.close()

    def clear(self):
        self.db.execute("PRAGMA secure_delete = ON")
        with self.db:
            self.db.execute("DELETE FROM messages")
            self.db.execute("DELETE FROM chats")
