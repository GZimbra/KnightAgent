"""Knowledge retrieval invariants; no network or model needed."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import json
import os
import sqlite3

from knightagent.knowledge import KnowledgeBase, SPECIALIZATION_PROMPT


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "knowledge.sqlite3"
        self.base = KnowledgeBase(self.path)
        self.addCleanup(self.base.close)

    def test_bundled_knowledge_is_available_offline_in_all_families(self):
        stats = self.base.stats()
        self.assertGreater(stats["documents"], 0)
        self.assertGreaterEqual(stats["chunks"], stats["documents"])
        for family in ("python", "vba", "office_scripts", "visual_basic"):
            with self.subTest(family=family):
                self.assertGreater(stats["families"][family]["documents"], 0)
        self.assertGreater(stats["bundled_documents"], 0)
        self.assertEqual(stats["official_documents"], 0)

    def test_reopening_does_not_duplicate_bundled_documents(self):
        before = self.base.stats()
        reopened = KnowledgeBase(self.path)
        self.addCleanup(reopened.close)
        after = reopened.stats()
        self.assertEqual(before["documents"], after["documents"])
        self.assertEqual(before["chunks"], after["chunks"])
        self.assertEqual(before["families"], after["families"])

    def test_python_automation_query_returns_reference_and_source(self):
        result = self.base.search("Python arquivos CSV pathlib automação")
        self.assertTrue(result)
        self.assertIn("docs.python.org", result)
        self.assertTrue("pathlib" in result or "csv" in result.lower())

    def test_vba_query_returns_excel_macro_guidance(self):
        result = self.base.search("VBA macro Excel Option Explicit")
        self.assertTrue(result)
        self.assertIn("learn.microsoft.com", result)
        self.assertIn("Option Explicit", result)

    def test_office_scripts_query_returns_typescript_api(self):
        result = self.base.search("Office Scripts ExcelScript getValues setValues")
        self.assertTrue(result)
        self.assertIn("ExcelScript", result)
        self.assertIn("learn.microsoft.com", result)

    def test_visual_basic_query_has_distinct_dotnet_source(self):
        result = self.base.search("Visual Basic .NET VB.NET Option Strict")
        self.assertTrue(result)
        self.assertIn("dotnet", result.lower())

    def test_search_empty_and_nonmatching_terms(self):
        for query in ("", "   ", "qzxxvvunfindabletoken833190"):
            with self.subTest(query=query):
                self.assertEqual(self.base.search(query), "")

    def test_search_bounds_long_context(self):
        query = "Python VBA Office Scripts automação arquivos CSV Excel"
        for chars in (600, 1200, 2400):
            with self.subTest(chars=chars):
                result = self.base.search(query, limit=4, max_chars=chars)
                self.assertLessEqual(len(result), chars)

    def test_query_punctuation_cannot_execute_fts_or_sql(self):
        before = self.base.stats()["documents"]
        for query in ('" OR * NEAR(:', "'; DROP TABLE documents; --", "(python) AND NOT {evil}"):
            with self.subTest(query=query):
                result = self.base.search(query)
                self.assertIsInstance(result, str)
        self.assertEqual(self.base.stats()["documents"], before)

    def test_search_works_across_gui_worker_threads(self):
        queries = ["Python csv", "VBA Excel", "Office Scripts", "VB.NET"] * 3
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self.base.search, queries))
        self.assertTrue(all(isinstance(result, str) and result for result in results))

    def test_default_initialization_and_queries_never_download(self):
        with patch("httpx.Client.request", side_effect=AssertionError("unexpected network")):
            offline = KnowledgeBase(Path(self.temp.name) / "offline.sqlite3")
            try:
                self.assertTrue(offline.search("Python arquivos csv"))
                self.assertGreater(offline.stats()["documents"], 0)
            finally:
                offline.close()

    def test_specialization_does_not_confuse_macros_and_scripts(self):
        self.assertIn("Python", SPECIALIZATION_PROMPT)
        self.assertIn("VBA", SPECIALIZATION_PROMPT)
        self.assertIn("Office Scripts", SPECIALIZATION_PROMPT)
        self.assertTrue("VB.NET" in SPECIALIZATION_PROMPT or "Visual Basic" in SPECIALIZATION_PROMPT)

    def test_online_sync_is_blocked_before_creating_any_network_client(self):
        with patch("httpx.Client", side_effect=AssertionError("unexpected client")), \
                patch("socket.create_connection", side_effect=AssertionError("unexpected socket")):
            for options in ({}, {"families": ["python"]}, {"max_pages": 5000}):
                with self.subTest(options=options), self.assertRaisesRegex(ValueError, "online foi removida"):
                    self.base.sync_official(**options)

    def test_import_txt_and_markdown_is_offline_searchable_and_idempotent(self):
        root = Path(self.temp.name)
        files = [root / "manual.txt", root / "procedimento.md"]
        files[0].write_text("DocLocalAcme Python movimentacao entrada em estoque.", encoding="utf-8")
        files[1].write_text("# Documento\nFluxoLocalAcme conferencia de etiquetas.", encoding="utf-8-sig")
        progress = []
        with patch("httpx.Client", side_effect=AssertionError("unexpected network")):
            report = self.base.import_local(files, progress=progress.append)
        self.assertEqual(report["documents_imported"], 2)
        self.assertEqual(report["documents_failed"], 0)
        self.assertEqual(report["families"]["local"]["imported"], 2)
        self.assertEqual(len(progress), 2)
        result = self.base.search("Python DocLocalAcme")
        self.assertIn("DocLocalAcme", result)
        self.assertIn(files[0].as_uri(), result)
        self.assertIn("FluxoLocalAcme", self.base.search("FluxoLocalAcme"))
        before = self.base.stats()
        self.base.import_local(files)
        after = self.base.stats()
        self.assertEqual(before["documents"], after["documents"])
        self.assertEqual(before["chunks"], after["chunks"])
        self.assertEqual(after["local_documents"], 2)

    def test_json_validates_entire_source_before_replacing_existing_documents(self):
        path = Path(self.temp.name) / "docs.json"
        path.write_text(json.dumps({"documents": [{"title": "Titulo", "text": "UniqueBeforeAcme", "family": "python"},
                                                 {"text": "UniqueSecondAcme"}]}), encoding="utf-8")
        self.assertEqual(self.base.import_local(path)["documents_imported"], 2)
        path.write_text(json.dumps({"documents": [{"text": "ReplacementAcme"}, {"text": 42}]}), encoding="utf-8")
        report = self.base.import_local(path)
        self.assertEqual(report["documents_imported"], 0)
        self.assertEqual(report["documents_failed"], 1)
        self.assertTrue(self.base.search("UniqueBeforeAcme"))
        self.assertFalse(self.base.search("ReplacementAcme"))
        path.write_text(json.dumps({"documents": [{"text": "ReplacementAcme", "family": "vba"}]}), encoding="utf-8")
        self.assertEqual(self.base.import_local(path)["documents_imported"], 1)
        self.assertEqual(self.base.stats()["local_documents"], 1)
        self.assertFalse(self.base.search("UniqueSecondAcme"))
        self.assertIn("[vba]", self.base.search("ReplacementAcme"))

    def test_legacy_official_sources_and_sync_metadata_survive_local_import(self):
        document = {"id": "official:legacy", "title": "Legado", "text": "LegacyUniqueAcme",
                    "family": "python", "url": "https://docs.python.org/legacy"}
        with closing(sqlite3.connect(self.path)) as db, db:
            self.base._store(db, document, "official")
            db.execute("INSERT INTO sync_runs VALUES(?,?)", ("python", '{"imported": 1}'))
        local = Path(self.temp.name) / "manual.txt"
        local.write_text("LocalUniqueAcme", encoding="utf-8")
        self.base.import_local(local)
        reopened = KnowledgeBase(self.path)
        self.assertTrue(reopened.search("LegacyUniqueAcme"))
        self.assertTrue(reopened.search("LocalUniqueAcme"))
        self.assertEqual(reopened.stats()["official_documents"], 1)
        self.assertEqual(reopened.stats()["last_sync"]["python"]["imported"], 1)

    def test_invalid_sources_are_reported_without_losing_successful_imports(self):
        root = Path(self.temp.name)
        cases = {"empty.md": b"  ", "binary.txt": b"a\x00b", "invalid.txt": b"\xff", "broken.json": b"{broken", "ok.txt": b"ValidLocalAcme"}
        for name, content in cases.items():
            (root / name).write_bytes(content)
        report = self.base.import_local([root / name for name in cases])
        self.assertEqual(report["documents_imported"], 1)
        self.assertEqual(report["documents_failed"], 4)
        self.assertEqual(len(report["failures"]), 4)
        self.assertTrue(self.base.search("ValidLocalAcme"))

    def test_directory_import_skips_unsupported_files_and_duplicate_paths(self):
        root = Path(self.temp.name) / "input"
        root.mkdir()
        (root / "nested").mkdir()
        (root / "nested" / "doc.md").write_text("NestedUniqueAcme", encoding="utf-8")
        (root / "skip.exe").write_bytes(b"not documentation")
        report = self.base.import_local([root, root / "nested" / "doc.md"])
        self.assertEqual(report["documents_imported"], 1)
        self.assertEqual(report["documents_skipped"], 2)
        self.assertEqual(report["documents_failed"], 0)

    def test_network_paths_refused_before_stat_or_open(self):
        paths = [r"\\server\share\doc.txt", "//server/share/doc.txt", "https://example.com/doc.txt"]
        with patch("pathlib.Path.lstat", side_effect=AssertionError("must reject before filesystem access")):
            report = self.base.import_local(paths)
        self.assertEqual(report["documents_failed"], 3)
        self.assertEqual(report["documents_imported"], 0)

    @unittest.skipUnless(os.name == "nt", "Windows drive types")
    def test_mapped_network_drive_is_refused_before_reading(self):
        with patch("ctypes.windll.kernel32.GetDriveTypeW", return_value=4), \
                patch("pathlib.Path.lstat", side_effect=AssertionError("must reject before filesystem access")):
            report = self.base.import_local([r"Z:\document.txt"])
        self.assertEqual(report["documents_failed"], 1)

    def test_reparse_point_is_refused(self):
        from types import SimpleNamespace
        with patch("pathlib.Path.lstat", return_value=SimpleNamespace(st_mode=0, st_file_attributes=0x400)):
            report = self.base.import_local([Path(self.temp.name) / "linked.txt"])
        self.assertEqual(report["documents_failed"], 1)
        self.assertIn("Links simbolicos", report["failures"][0]["reason"])

    def test_size_bound_prevents_opening_large_file(self):
        path = Path(self.temp.name) / "big.txt"
        path.write_text("x" * 100, encoding="utf-8")
        with patch("knightagent.knowledge.MAX_FILE_BYTES", 50), \
                patch("pathlib.Path.open", side_effect=AssertionError("oversized file must not be opened")):
            report = self.base.import_local(path)
        self.assertEqual(report["documents_failed"], 1)

    def test_total_size_bound_preserves_preceding_committed_files(self):
        paths = [Path(self.temp.name) / "a.txt", Path(self.temp.name) / "b.txt"]
        for path in paths:
            path.write_text("x" * 50, encoding="utf-8")
        with patch("knightagent.knowledge.MAX_IMPORT_BYTES", 75):
            report = self.base.import_local(paths)
        self.assertEqual(report["documents_imported"], 1)
        self.assertEqual(report["documents_failed"], 1)

    def test_json_supports_plain_data_and_local_provenance_only(self):
        path = Path(self.temp.name) / "plain.json"
        path.write_text('{"codigo": "ArmazemUniqueAcme", "quantidade": 7}', encoding="utf-8")
        self.assertEqual(self.base.import_local(path)["documents_imported"], 1)
        self.assertIn("ArmazemUniqueAcme", self.base.search("ArmazemUniqueAcme"))
        path.write_text('{"text": "NewUniqueAcme", "url": "https://external.test", "id": "bundled:python-json-configuracao"}', encoding="utf-8")
        self.base.import_local(path)
        result = self.base.search("NewUniqueAcme")
        self.assertIn(path.as_uri(), result)
        self.assertNotIn("external.test", result)

    def test_import_argument_validation(self):
        for paths in ([], None, [None], {}):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.base.import_local(paths)
        with self.assertRaises(ValueError):
            self.base.import_local(["x.txt"], family="Invalid FAMILY")


if __name__ == "__main__":
    unittest.main()
