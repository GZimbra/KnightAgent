import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import stat

from knightagent.tools.files import FileTools, Workspace, WriteApproval, FileSafetyError


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.logs = []
        self.tools = FileTools(Workspace(self.root), WriteApproval(lambda _: "s", self.logs.append))

    def test_vba_cp1252_crlf_create_and_edit(self):
        for ext in ("bas", "cls"):
            path = "Modulo." + ext
            self.tools.create_file(path, 'Option Explicit\n\' ação\n')
            self.assertEqual((self.root / path).read_bytes(), "Option Explicit\r\n' ação\r\n".encode("cp1252"))
            self.tools.edit_file(path, "ação", "revisão")
            self.assertEqual((self.root / path).read_bytes(), "Option Explicit\r\n' revisão\r\n".encode("cp1252"))
            self.assertIn("revisão", self.tools.read_file(path))

    def test_vba_unrepresentable_no_write(self):
        self.assertTrue(self.tools.execute("create_file", {"path": "x.bas", "content": "😀"}).startswith("ERRO"))
        self.assertFalse((self.root / "x.bas").exists())
        self.assertEqual(self.logs, [])

    def test_yaml_artifact_is_saved_as_utf8(self):
        outcome = self.tools.create_file("automacao.yaml", "tarefa: saudação\n")
        self.assertIn("SALVO", outcome)
        self.assertEqual((self.root / "automacao.yaml").read_bytes(), "tarefa: saudação\n".encode("utf-8"))

    def test_windows_unsafe_paths(self):
        for path in ("../outside", "..\\outside", "C:\\outside", "c:outside", "\\outside", "\\\\server\\share\\x", "\\\\?\\C:\\x", "x:stream", "NUL", "con.txt", "COM1.bas", "lpt9.txt", "COM¹.txt", "foo.", "foo ", "a/../../b"):
            with self.subTest(path=path), self.assertRaises(FileSafetyError):
                self.tools.workspace.path(path)

    @unittest.skipUnless(os.name == "nt", "Windows")
    def test_windows_case_insensitive(self):
        (self.root / "MiXeD.txt").write_text("ok")
        self.assertIn("ok", self.tools.read_file("mixed.TXT"))

    @unittest.skipUnless(os.name == "nt", "Windows junction")
    def test_junction_outside_blocked_and_search_skips(self):
        with tempfile.TemporaryDirectory() as outside:
            Path(outside, "secret.txt").write_text("secret")
            link = self.root / "junction"
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), outside], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                with self.assertRaises(FileSafetyError):
                    self.tools.workspace.path("junction/secret.txt")
                self.assertNotIn("secret.txt", self.tools.search_text(".", "secret"))
            finally:
                link.rmdir()

    def test_symlink_outside(self):
        with tempfile.TemporaryDirectory() as outside:
            try:
                (self.root / "link").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Sistema nao permite criar symlink neste token")
            with self.assertRaises(FileSafetyError):
                self.tools.workspace.path("link/x.txt")

    def test_symlink_mode_blocked_without_os_privilege(self):
        with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)):
            with self.assertRaises(FileSafetyError):
                self.tools.workspace.path("link/file.txt")

    def test_hardlink_outside_blocked(self):
        with tempfile.TemporaryDirectory() as outside:
            source = Path(outside, "data.txt")
            source.write_text("private")
            os.link(source, self.root / "alias.txt")
            with self.assertRaises(FileSafetyError):
                self.tools.workspace.path("alias.txt")

    def test_refusal_and_session_approval(self):
        self.tools.approval = WriteApproval(lambda _: "n", self.logs.append)
        self.assertIn("RECUSADO", self.tools.create_file("a.txt", "x"))
        self.assertFalse((self.root / "a.txt").exists())
        calls = []
        self.tools.approval = WriteApproval(lambda _: calls.append(1) or "t", self.logs.append)
        self.tools.create_file("a.txt", "x")
        self.tools.create_file("b.txt", "y")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.logs), 3)

    def test_concurrent_change_during_approval(self):
        (self.root / "x.txt").write_text("old")
        def changed(_):
            (self.root / "x.txt").write_text("another writer")
            return "s"
        self.tools.approval = WriteApproval(changed, self.logs.append)
        self.assertIn("mudou", self.tools.edit_file("x.txt", "old", "new"))
        self.assertEqual((self.root / "x.txt").read_text(), "another writer")

    def test_chunks_search_and_unique_replacement(self):
        (self.root / "large.txt").write_text("x" * 20000, encoding="utf-8")
        text = self.tools.read_file("large.txt", offset=100, length=100)
        self.assertIn("next_offset=200", text)
        self.assertIn("TRECHO LIMITADO", text)
        self.assertIn("large.txt", self.tools.search_text(".", "xxx"))
        self.assertIn("exatamente", self.tools.edit_file("large.txt", "x", "y"))
        self.assertIn("large.txt", self.tools.list_directory("."))
        self.assertIn("SALVO", self.tools.create_file("large.txt", "oops"))
        self.assertEqual((self.root / "large.txt").read_text(encoding="utf-8"), "oops")

    def test_recreate_existing_file_requires_diff_approval(self):
        target = self.root / "macro.bas"
        target.write_bytes(b"Sub Old()\r\nEnd Sub\r\n")
        approvals = []
        self.tools.approval = WriteApproval(lambda _: approvals.append(True) or "s", self.logs.append)
        self.assertIn("SALVO", self.tools.create_file("macro.bas", "Sub New()\nEnd Sub\n"))
        self.assertEqual(len(approvals), 1)
        self.assertIn("-Sub Old()", self.logs[-1])
        self.assertIn("+Sub New()", self.logs[-1])
        self.assertEqual(target.read_bytes(), b"Sub New()\r\nEnd Sub\r\n")
