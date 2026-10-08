"""Bounded local document import and SQLite retrieval; no internet access."""

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import unicodedata

from .corpus import BUNDLED_DOCS, SPECIALIZATION_PROMPT


MAX_FILE_BYTES = 4_000_000
MAX_IMPORT_BYTES = 32_000_000
MAX_IMPORT_FILES = 1000
MAX_JSON_DOCUMENTS = 1000
SUPPORTED_EXTENSIONS = {".txt", ".md", ".json"}


STOP = set("a an the and or to of for in is as de do da dos das que para por como com uma um os as crie criar gere gerar preciso quero codigo script automacao simples basica intermediaria usando somente use arquivo arquivos".split())
ALIASES = {"copiar": "copy", "colunas": "columns", "linhas": "rows", "planilha": "worksheet", "planilhas": "worksheets",
           "pasta": "pathlib", "pastas": "pathlib", "csv": "DictReader", "tabela": "table", "tabelas": "table",
           "json": "json", "erro": "exception", "erros": "exception", "datas": "datetime", "macro": "vba"}


def _plain(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))



def _local_path(value):
    """Check roots and every parent before following a filesystem reference."""
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or raw.startswith(("\\\\", "//")) or "://" in raw:
        raise ValueError("Use arquivos em disco local; URLs e caminhos de rede sao bloqueados.")
    path = Path(os.path.abspath(os.path.expanduser(raw)))
    if os.name == "nt":
        import ctypes
        # A mapped network drive can look like a local drive; reject before stat.
        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4:
            raise ValueError("Unidades de rede nao sao permitidas.")
    for part in (*reversed(path.parents), path):
        details = part.lstat()
        if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
            raise ValueError("Links simbolicos, junctions e arquivos remotos nao sao importados.")
    return path


def _family(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", value):
        raise ValueError("Familia invalida; use letras minusculas, numeros e sublinhado (ate 50 caracteres).")
    return value


def _documents_from_file(path, family, raw):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Codificacao invalida; salve o documento como UTF-8.") from None
    if "\x00" in text or not text.strip():
        raise ValueError("Documento vazio ou binario.")
    entries = [{"title": path.stem, "text": text}]
    if path.suffix.lower() == ".json":
        try:
            parsed = json.loads(text)
        except (ValueError, RecursionError):
            raise ValueError("JSON invalido.") from None
        if isinstance(parsed, dict) and "documents" in parsed:
            entries = parsed["documents"]
        elif isinstance(parsed, dict) and "text" in parsed:
            entries = [parsed]
        elif isinstance(parsed, list) and any(isinstance(item, dict) and "text" in item for item in parsed):
            entries = parsed
        else:
            entries = [{"title": path.stem, "text": json.dumps(parsed, ensure_ascii=False, indent=2)}]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_JSON_DOCUMENTS:
        raise ValueError("JSON deve conter de 1 a 1000 documentos.")
    source = path.as_uri()
    key = sha256(os.path.normcase(str(path)).encode("utf-8")).hexdigest()
    documents = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError("Cada documento JSON deve ser um objeto com texto.")
        content, title = entry.get("text"), entry.get("title", path.stem)
        if not isinstance(content, str) or not content.strip() or "\x00" in content:
            raise ValueError("Cada documento deve conter text nao vazio, sem dados binarios.")
        if not isinstance(title, str) or not title.strip() or len(title) > 300:
            raise ValueError("Titulo deve conter de 1 a 300 caracteres.")
        documents.append({"id": f"local:{key}:{index}", "family": _family(entry.get("family", family)),
                          "title": title.strip(), "url": source, "text": content.strip()})
    return documents


class KnowledgeBase:
    def __init__(self, path):
        self.path = Path(path)
        self.last_document_ids = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._open()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, family TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL, origin TEXT NOT NULL, digest TEXT NOT NULL, updated_at TEXT NOT NULL)")
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(document_id UNINDEXED, title, text, tokenize='unicode61 remove_diacritics 2')")
            db.execute("CREATE TABLE IF NOT EXISTS sync_runs(family TEXT PRIMARY KEY, report TEXT NOT NULL)")
            for document in BUNDLED_DOCS:
                self._store(db, {**document, "id": "bundled:" + document["id"]}, "bundled")

    def _open(self):
        return sqlite3.connect(self.path, timeout=30)

    def close(self):
        """Connections are scoped to operations, including across GUI worker threads."""

    @staticmethod
    def _store(db, document, origin):
        text = document["text"].strip()
        digest = sha256(json.dumps([document["family"], document["title"], document["url"], text], ensure_ascii=False).encode("utf-8")).hexdigest()
        old = db.execute("SELECT digest FROM documents WHERE id=?", (document["id"],)).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        if old and old[0] == digest:
            db.execute("UPDATE documents SET updated_at=? WHERE id=?", (now, document["id"]))
            return
        db.execute("DELETE FROM chunks WHERE document_id=?", (document["id"],))
        db.execute("INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?,?)",
                   (document["id"], document["family"], document["title"], document["url"], origin, digest, now))
        offset = 0
        while offset < len(text):
            end = min(offset + 2600, len(text))
            if end < len(text):
                boundary = text.rfind("\n", offset + 1500, end)
                if boundary > offset:
                    end = boundary
            db.execute("INSERT INTO chunks(document_id,title,text) VALUES(?,?,?)", (document["id"], document["title"], text[offset:end]))
            if end == len(text):
                break
            offset = end - 180

    def stats(self):
        with closing(self._open()) as db:
            families = {family: {"documents": count, "chunks": 0} for family, count in db.execute("SELECT family, COUNT(*) FROM documents GROUP BY family")}
            for family, count in db.execute("SELECT d.family, COUNT(*) FROM chunks c JOIN documents d ON c.document_id=d.id GROUP BY d.family"):
                families[family]["chunks"] = count
            origins = dict(db.execute("SELECT origin, COUNT(*) FROM documents GROUP BY origin"))
            return {"documents": sum(origins.values()), "chunks": db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                    "bundled_documents": origins.get("bundled", 0), "official_documents": origins.get("official", 0),
                    "local_documents": origins.get("local", 0),
                    "families": families, "last_sync": {family: json.loads(report) for family, report in db.execute("SELECT family, report FROM sync_runs")}}

    def search(self, query, limit=4, max_chars=6000):
        self.last_document_ids = []
        if not isinstance(query, str) or type(limit) is not int or not 1 <= limit <= 20 or type(max_chars) is not int or not 1 <= max_chars <= 20000:
            raise ValueError("Parametros de busca invalidos.")
        plain = _plain(query)
        words = list(dict.fromkeys(word for word in re.findall(r"[a-z0-9_]{2,}", plain) if word not in STOP))[:20]
        if not words:
            return ""
        terms = list(dict.fromkeys(words + [ALIASES[word] for word in words if word in ALIASES]))
        families = []
        if "python" in words:
            families.append("python")
        if "vba" in words or "macro" in words or "macros" in words:
            families.append("vba")
        if "office script" in plain or "officescript" in plain or "excelscript" in plain or "typescript" in plain:
            families.append("office_scripts")
        if "vb.net" in plain or "vbnet" in plain or "visual basic" in plain and "vba" not in words:
            families.append("visual_basic")
        match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        sql = "SELECT d.id,d.title,d.url,d.family,c.text FROM chunks c JOIN documents d ON c.document_id=d.id WHERE chunks MATCH ?"
        parameters = [match]
        if families:
            sql += " AND (d.family IN (" + ",".join("?" for _ in families) + ") OR d.origin='local')"
            parameters.extend(families)
        sql += " ORDER BY bm25(chunks,0,6,1) LIMIT ?"
        parameters.append(limit * 8)
        with closing(self._open()) as db:
            rows = db.execute(sql, parameters).fetchall()
        selected, seen = [], set()
        for row in rows:
            if row[0] not in seen:
                selected.append(row)
                seen.add(row[0])
            if len(selected) == limit:
                break
        pieces, remaining = [], max_chars
        for document_id, title, url, family, text in selected:
            header = f"[{family}] {title}\nFonte local armazenada (sem consulta online): {url}\n"
            allowance = min(remaining, max_chars // max(1, len(selected)))
            if allowance <= len(header) + 40:
                continue
            piece = (header + text[:allowance - len(header) - 2] + "\n\n")[:remaining]
            pieces.append(piece)
            self.last_document_ids.append(document_id)
            remaining -= len(piece)
        return "".join(pieces)

    def import_local(self, paths, family="local", progress=None):
        """Validate each local source before its atomic replacement in SQLite."""
        family = _family(family)
        if isinstance(paths, (str, os.PathLike)):
            paths = [paths]
        if not isinstance(paths, (tuple, list)) or not paths or len(paths) > MAX_IMPORT_FILES:
            raise ValueError("Selecione de 1 a 1000 arquivos ou pastas locais.")
        if any(not isinstance(path, (str, os.PathLike)) for path in paths):
            raise ValueError("Origens devem ser caminhos de arquivos ou pastas locais.")
        if progress is not None and not callable(progress):
            raise ValueError("Callback de progresso invalido.")
        report = {"documents_imported": 0, "documents_failed": 0, "documents_skipped": 0,
                  "failures": [], "families": {}}
        seen, total_bytes, inspected = set(), 0, 0
        pending = list(reversed(paths))

        def failure(path, reason):
            report["documents_failed"] += 1
            if len(report["failures"]) < 100:
                report["failures"].append({"path": os.fspath(path), "reason": reason})
            if progress:
                progress(f"Falha: {path}: {reason}")

        while pending:
            value = pending.pop()
            inspected += 1
            if inspected > MAX_IMPORT_FILES:
                failure(value, "Limite de 1000 entradas por importacao atingido; selecione pastas menores.")
                break
            try:
                path = _local_path(value)
                identity = os.path.normcase(str(path))
                if identity in seen:
                    report["documents_skipped"] += 1
                    continue
                seen.add(identity)
                if path.is_dir():
                    with os.scandir(path) as entries:
                        children = []
                        for entry in entries:
                            if len(children) + len(pending) + inspected >= MAX_IMPORT_FILES:
                                raise ValueError("Pasta excede o limite de 1000 entradas; selecione uma subpasta.")
                            children.append(Path(entry.path))
                    pending.extend(reversed(sorted(children)))
                    continue
                if not path.is_file():
                    raise ValueError("A origem nao e um arquivo comum.")
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    report["documents_skipped"] += 1
                    continue
                size = path.stat().st_size
                if size > MAX_FILE_BYTES:
                    raise ValueError("Arquivo excede o limite de 4 MB.")
                if total_bytes + size > MAX_IMPORT_BYTES:
                    raise ValueError("Importacao excede o limite de 32 MB; use lotes menores.")
                _local_path(path)
                with path.open("rb") as source:
                    raw = source.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES or total_bytes + len(raw) > MAX_IMPORT_BYTES:
                    raise ValueError("Arquivo mudou de tamanho ou excede o limite da importacao.")
                total_bytes += len(raw)
                documents = _documents_from_file(path, family, raw)
                with closing(self._open()) as db, db:
                    old_ids = [row[0] for row in db.execute(
                        "SELECT id FROM documents WHERE origin='local' AND url=?", (path.as_uri(),))]
                    db.executemany("DELETE FROM chunks WHERE document_id=?", [(key,) for key in old_ids])
                    db.executemany("DELETE FROM documents WHERE id=?", [(key,) for key in old_ids])
                    for document in documents:
                        self._store(db, document, "local")
                report["documents_imported"] += len(documents)
                for document in documents:
                    counts = report["families"].setdefault(document["family"], {"imported": 0})
                    counts["imported"] += 1
                if progress:
                    progress(f"Importado: {path.name} ({len(documents)} documento(s)).")
            except (OSError, ValueError, sqlite3.Error) as error:
                reason = str(error) if isinstance(error, ValueError) else f"Nao foi possivel ler ou armazenar a origem ({type(error).__name__})."
                failure(value, reason)
        return report

    def sync_official(self, families=None, *, max_pages=1200, progress=None, timeout=25.0):
        """Compatibility entry point: online synchronization is permanently disabled."""
        raise ValueError("A sincronizacao online foi removida. Use import_local com arquivos no disco local.")
