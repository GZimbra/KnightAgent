import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from knightagent.copilot_client import CopilotClient, CopilotClientError, public_settings
from knightagent.copilot_helper import _start_parent_watchdog, _watch_parent, dispatch, main


CLIENT_ID = "c338074d-3ae2-4ad6-bb03-fdb28e870621"
SETTINGS = {"client_id": CLIENT_ID, "tenant": "organizations"}


def protocol_result(result):
    return json.dumps({"version": 1, "result": result}, ensure_ascii=False).encode("utf-8")


def fake_process(output=None, returncode=0):
    process = Mock()
    process.returncode = returncode
    process.poll.return_value = returncode
    process.communicate.return_value = (output or protocol_result({"status": "disconnected", "message": "Não conectado"}), None)
    return process


class CopilotClientTests(unittest.TestCase):
    def setUp(self):
        self.client = CopilotClient(Path("config.yaml"), SETTINGS)

    def test_client_keeps_only_public_settings_in_ipc(self):
        settings = {**SETTINGS, "copilot": True, "mode": "account", "access_token": "PRIVATE"}
        self.assertEqual(public_settings(settings), SETTINGS)
        for invalid in (None, [], {"client_id": "bad"}, {"tenant": "common"}, {"client_id": None}):
            with self.subTest(invalid=invalid), self.assertRaises(CopilotClientError):
                public_settings(invalid)

    @patch("knightagent.copilot_client.subprocess.Popen")
    @patch("socket.create_connection")
    def test_no_client_id_means_no_subprocess_and_no_network(self, connection, popen):
        client = CopilotClient("config.yaml", {})
        for method in (client.status, client.login, client.logout, client.verify_access):
            self.assertEqual(method()["status"], "setup_required")
        with self.assertRaises(CopilotClientError):
            client.consult("Ajuda")
        popen.assert_not_called()
        connection.assert_not_called()

    @patch("knightagent.copilot_client.subprocess.Popen")
    def test_protocol_is_utf8_no_shell_and_no_token_fields(self, popen):
        process = fake_process(protocol_result({"status": "authenticated", "message": "Conectado", "account": "conta@example.test", "access_token": "PRIVATE"}))
        popen.return_value = process
        response = self.client.status()
        self.assertNotIn("PRIVATE", str(response))
        self.assertEqual(set(response), {"status", "message", "account"})
        args, kwargs = popen.call_args
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(kwargs["cwd"], str(Path("config.yaml").resolve().parent))
        self.assertIn("-I", args[0])
        request = json.loads(process.communicate.call_args.args[0].decode("utf-8"))
        self.assertEqual(request, {"version": 1, "operation": "status", "settings": SETTINGS})
        self.assertEqual(process.communicate.call_args.kwargs["timeout"], 30)
        process.stdin.close.assert_called_once()
        process.stdout.close.assert_called_once()
        self.assertIsNone(self.client._process)

    def test_development_helper_import_does_not_depend_on_workspace(self):
        command = self.client._command()
        self.assertEqual(command[:4], [sys.executable, "-I", "-u", "-m"])
        self.assertEqual(command[4], "knightagent.copilot_helper")

    @patch("knightagent.copilot_client.subprocess.Popen")
    def test_invalid_prompts_never_launch_child(self, popen):
        for prompt in (None, "", " ", "a" * 6001, {}):
            with self.subTest(prompt_type=type(prompt)), self.assertRaises(CopilotClientError):
                self.client.consult(prompt)
        with self.assertRaises(CopilotClientError):
            self.client._request("invalid")
        popen.assert_not_called()

    @patch("knightagent.copilot_client.subprocess.Popen")
    def test_consult_keeps_valid_6000_character_response(self, popen):
        popen.return_value = fake_process(protocol_result("a" * 6000))
        self.assertEqual(self.client.consult("ação"), "a" * 6000)
        request = json.loads(popen.return_value.communicate.call_args.args[0])
        self.assertEqual(request["prompt"], "ação")
        self.assertEqual(popen.return_value.communicate.call_args.kwargs["timeout"], 125)

    @patch("knightagent.copilot_client.subprocess.Popen")
    def test_invalid_and_oversized_protocol_responses_are_rejected(self, popen):
        for output in (b"not-json", b"\xff", b"[]", b"x" * 100001,
                       b'{"version":true,"result":{"status":"ready"}}',
                       b'{"version":1,"extra":"PRIVATE","result":{"status":"ready"}}',
                       protocol_result({"status": "unknown"}),
                       protocol_result({"status": "ready", "account": {"token": "PRIVATE"}})):
            with self.subTest(output=output[:60]), self.assertRaises(CopilotClientError) as captured:
                popen.return_value = fake_process(output)
                self.client.status()
            self.assertNotIn("PRIVATE", str(captured.exception))
        for output in (protocol_result(""), protocol_result("a" * 6001), protocol_result({"status": "ready"})):
            popen.return_value = fake_process(output)
            with self.assertRaises(CopilotClientError):
                self.client.consult("Pergunta")

    @patch("knightagent.copilot_client.subprocess.Popen")
    def test_child_error_text_is_not_exposed(self, popen):
        popen.return_value = fake_process(b'{"version":1,"error":"PRIVATE TOKENS"}')
        with self.assertRaises(CopilotClientError) as captured:
            self.client.consult("Pergunta")
        self.assertNotIn("PRIVATE", str(captured.exception))

    @patch("knightagent.copilot_client.subprocess.Popen")
    def test_timeout_kills_reaps_and_closes_child_without_second_communicate(self, popen):
        process = fake_process()
        process.poll.return_value = None
        process.communicate.side_effect = subprocess.TimeoutExpired("helper", 30)
        popen.return_value = process
        with self.assertRaises(CopilotClientError) as captured:
            self.client.login()
        self.assertIn("tempo", str(captured.exception))
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=1)
        self.assertEqual(process.communicate.call_count, 1)
        process.stdin.close.assert_called_once()
        process.stdout.close.assert_called_once()
        self.assertIsNone(self.client._process)

    @patch("knightagent.copilot_client.subprocess.Popen")
    def test_cleanup_reaps_child_after_io_failure(self, popen):
        process = fake_process()
        process.poll.return_value = None
        process.communicate.side_effect = OSError("PRIVATE")
        popen.return_value = process
        with self.assertRaises(CopilotClientError) as captured:
            self.client.status()
        self.assertNotIn("PRIVATE", str(captured.exception))
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=1)

    @patch("knightagent.copilot_client.subprocess.Popen")
    def test_close_cancels_inflight_and_future_requests(self, popen):
        process = fake_process()
        process.poll.return_value = None
        entered = threading.Event()
        released = threading.Event()
        failures = []

        def communicate(*args, **kwargs):
            entered.set()
            if not released.wait(3):
                raise AssertionError("test worker did not receive cancellation")
            return protocol_result({"status": "ready"}), None

        def request():
            try:
                self.client.status()
            except CopilotClientError as error:
                failures.append(str(error))

        process.communicate.side_effect = communicate
        process.terminate.side_effect = released.set
        popen.return_value = process
        worker = threading.Thread(target=request)
        worker.start()
        self.assertTrue(entered.wait(3))
        self.client.close()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        process.terminate.assert_called_once()
        self.assertEqual(len(failures), 1)
        self.assertIn("cancelada", failures[0])
        with self.assertRaises(CopilotClientError):
            self.client.login()
        popen.assert_called_once()

    def test_close_escalates_only_its_own_unresponsive_child(self):
        process = fake_process()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("helper", 1), None]
        self.client._process = process
        self.client.close()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)


class CopilotHelperTests(unittest.TestCase):
    @patch("knightagent.copilot_helper.os._exit")
    def test_watchdog_exits_only_self_when_parent_ends_or_wait_fails(self, terminate_self):
        for result in (0, 0xFFFFFFFF):
            with self.subTest(result=result):
                wait = Mock(side_effect=[258, result])
                close = Mock()
                _watch_parent(123, wait, close)
                self.assertEqual(wait.call_count, 2)
                wait.assert_called_with(123, 1000)
                close.assert_called_once_with(123)
                terminate_self.assert_called_with(1)
        self.assertEqual(terminate_self.call_count, 2)

    @unittest.skipUnless(sys.platform == "win32", "Windows process handles are required")
    @patch("knightagent.copilot_helper.sys.frozen", True, create=True)
    @patch("knightagent.copilot_helper.threading.Thread")
    @patch("ctypes.WinDLL")
    def test_frozen_helper_monitors_parent_with_synchronize_only(self, win_dll, thread):
        kernel = win_dll.return_value
        kernel.OpenProcess.return_value = 123
        with patch("knightagent.copilot_helper.os.getppid", return_value=456):
            _start_parent_watchdog()
        kernel.OpenProcess.assert_called_once_with(0x00100000, False, 456)
        self.assertTrue(thread.call_args.kwargs["daemon"])
        self.assertIs(thread.call_args.kwargs["target"], _watch_parent)
        self.assertEqual(thread.call_args.kwargs["args"][0], 123)
        thread.return_value.start.assert_called_once()

    @unittest.skipUnless(sys.platform == "win32", "Windows process handles are required")
    @patch("knightagent.copilot_helper.sys.frozen", True, create=True)
    @patch("ctypes.WinDLL")
    def test_frozen_helper_fails_closed_if_parent_handle_unavailable(self, win_dll):
        win_dll.return_value.OpenProcess.return_value = None
        with self.assertRaises(RuntimeError):
            _start_parent_watchdog()

    @patch("knightagent.copilot_helper._start_parent_watchdog", side_effect=RuntimeError("unavailable"))
    @patch("knightagent.copilot_helper.dispatch")
    def test_watchdog_must_start_before_processing_any_auth_request(self, dispatcher, watchdog):
        stdin = SimpleNamespace(buffer=io.BytesIO(b'{"version":1,"operation":"login"}'))
        stdout = SimpleNamespace(buffer=io.BytesIO())
        with patch("knightagent.copilot_helper.sys.stdin", stdin), patch("knightagent.copilot_helper.sys.stdout", stdout):
            main()
        dispatcher.assert_not_called()
        self.assertEqual(json.loads(stdout.buffer.getvalue())["error"], "copilot_unavailable")

    @patch("knightagent.copilot_auth.CopilotService")
    def test_protocol_validation_precedes_service_construction(self, service):
        base = {"version": 1, "operation": "status", "settings": SETTINGS}
        for request in (None, [], {**base, "version": True}, {**base, "version": 2},
                        {**base, "operation": "shell"}, {**base, "operation": []},
                        {**base, "secret": "PRIVATE"}, {**base, "prompt": "ignored"},
                        {**base, "operation": "consult", "prompt": "a" * 6001}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                dispatch(request)
        service.assert_not_called()

    @patch("knightagent.copilot_auth.CopilotService")
    def test_consult_dispatch_passes_only_supplied_prompt(self, service):
        service.return_value.consult.return_value = "Resposta"
        result = dispatch({"version": 1, "operation": "consult", "settings": SETTINGS, "prompt": "Pergunta"})
        self.assertEqual(result, "Resposta")
        service.assert_called_once_with(SETTINGS)
        service.return_value.consult.assert_called_once_with("Pergunta")

    @patch("socket.create_connection")
    def test_unconfigured_helper_has_local_setup_result(self, connection):
        result = dispatch({"version": 1, "operation": "status", "settings": {}})
        self.assertEqual(result["status"], "setup_required")
        connection.assert_not_called()

    @patch("knightagent.copilot_helper.dispatch")
    def test_main_bounds_input_and_sanitizes_internal_failures(self, dispatcher):
        for raw in (b"x" * 64001, b"not-json", b'{"version":1}'):
            input_stream = SimpleNamespace(buffer=io.BytesIO(raw))
            output_stream = SimpleNamespace(buffer=io.BytesIO())
            dispatcher.side_effect = RuntimeError("PRIVATE TOKEN")
            with patch("knightagent.copilot_helper.sys.stdin", input_stream), patch("knightagent.copilot_helper.sys.stdout", output_stream):
                self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output_stream.buffer.getvalue()), {"version": 1, "error": "copilot_unavailable"})

    def test_real_isolated_subprocess_handles_unconfigured_status(self):
        request = json.dumps({"version": 1, "operation": "status", "settings": {}}).encode()
        with tempfile.TemporaryDirectory() as directory:
            # A workspace module with this name must never shadow the app.
            (Path(directory) / "knightagent.py").write_text("raise RuntimeError('workspace shadow')", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-I", "-u", "-m", "knightagent.copilot_helper"],
                input=request, capture_output=True, cwd=directory, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["result"]["status"], "setup_required")
        self.assertEqual(result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
