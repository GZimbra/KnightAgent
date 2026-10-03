from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx
import msal

from knightagent.copilot_auth import (
    CopilotError, CopilotService, GRAPH_URL, LOGIN_TIMEOUT,
    MAX_RESPONSE_CHARS, SCOPES, _AuthHTTP, normalize_settings,
)


CLIENT_ID = "c338074d-3ae2-4ad6-bb03-fdb28e870621"
CONVERSATION_ID = "0d110e7e-2b7e-4270-a899-fd2af6fde333"
SETTINGS = {"client_id": CLIENT_ID, "tenant": "organizations"}
ACCOUNT = {
    "home_account_id": "user.tenant", "environment": "login.microsoftonline.com",
    "realm": "tenant", "local_account_id": "user", "username": "user@example.test",
    "authority_type": "MSSTS",
}


def account_cache():
    cache = msal.SerializableTokenCache()
    cache.modify("Account", ACCOUNT, ACCOUNT)
    return cache


class CopilotAuthTests(unittest.TestCase):
    def setUp(self):
        self.service = CopilotService(SETTINGS)

    def test_only_public_identifiers_are_accepted(self):
        self.assertEqual(normalize_settings({}), {"client_id": "", "tenant": "organizations"})
        self.assertEqual(normalize_settings({"client_id": CLIENT_ID.upper()})["client_id"], CLIENT_ID)
        for settings in (
            {"client_secret": "secret"}, {"access_token": "token"},
            {"client_id": "bad-id"}, {"tenant": "common"},
            {"tenant": "https://evil.test"}, {"client_id": 42},
        ):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                normalize_settings(settings)

    @patch("knightagent.copilot_auth.httpx.Client")
    @patch("msal.PublicClientApplication")
    def test_unconfigured_operations_never_start_network_or_auth(self, app, client):
        service = CopilotService({})
        for action in (service.status, service.login, service.logout, service.verify_access):
            self.assertEqual(action()["status"], "setup_required")
        with self.assertRaises(CopilotError) as captured:
            service.consult("ajuda")
        self.assertEqual(captured.exception.status, "setup_required")
        app.assert_not_called()
        client.assert_not_called()

    @patch("msal.PublicClientApplication")
    @patch("knightagent.copilot_auth.httpx.Client")
    def test_status_only_reads_cached_account_no_silent_refresh(self, client, app):
        with patch.object(self.service, "_load_cache", return_value=account_cache()):
            result = self.service.status()
        self.assertEqual(result["status"], "authenticated")
        self.assertEqual(result["account"], ACCOUNT["username"])
        self.assertEqual(set(result), {"status", "account", "message"})
        app.assert_not_called()
        client.assert_not_called()

    def test_missing_cache_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-created" / "cache.bin"
            with patch.object(self.service, "_path", return_value=path):
                self.assertEqual(self.service.status()["status"], "disconnected")
            self.assertFalse(path.parent.exists())

    def test_login_uses_interactive_select_account_and_persists_only_after_success(self):
        app = Mock()

        @contextmanager
        def application(cache):
            def authenticate(**kwargs):
                cache.modify("Account", ACCOUNT, ACCOUNT)
                return {"access_token": "never-return-this", "id_token": "never-return-id"}
            app.acquire_token_interactive.side_effect = authenticate
            yield app

        with patch.object(self.service, "_application", side_effect=application), patch.object(self.service, "_save_cache") as save:
            result = self.service.login()
        self.assertEqual(result["status"], "authenticated")
        self.assertNotIn("never-return", json.dumps(result))
        app.acquire_token_interactive.assert_called_once_with(scopes=SCOPES, prompt="select_account", timeout=LOGIN_TIMEOUT)
        self.assertEqual(json.loads(save.call_args.args[0])["Account"].popitem()[1]["username"], ACCOUNT["username"])
        app.acquire_token_silent_with_error.assert_not_called()

    def test_cancelled_switch_preserves_previous_cache_and_hides_raw_description(self):
        app = Mock()
        app.acquire_token_interactive.return_value = {"error": "access_denied", "error_description": "SECRET TOKEN credential details"}
        with patch.object(self.service, "_application") as application, patch.object(self.service, "_save_cache") as save:
            application.return_value.__enter__.return_value = app
            result = self.service.login()
        self.assertEqual(result["status"], "access_denied")
        self.assertNotIn("SECRET", str(result))
        save.assert_not_called()

    def test_admin_consent_error_is_actionable_without_raw_identity(self):
        app = Mock()
        app.acquire_token_interactive.return_value = {"error": "invalid_grant", "error_codes": [65001], "error_description": "user secret"}
        with patch.object(self.service, "_application") as application:
            application.return_value.__enter__.return_value = app
            result = self.service.login()
        self.assertEqual(result["status"], "consent_required")
        self.assertIn("administrador", result["message"])
        self.assertNotIn("user secret", str(result))

    def test_silent_session_expiry_does_not_open_browser(self):
        app = Mock()
        app.acquire_token_silent_with_error.return_value = None
        with patch.object(self.service, "_application") as application, patch.object(self.service, "_load_cache", return_value=account_cache()):
            application.return_value.__enter__.return_value = app
            with self.assertRaises(CopilotError) as captured:
                self.service.consult("responda")
        self.assertEqual(captured.exception.status, "session_expired")
        app.acquire_token_interactive.assert_not_called()

    def _consult(self, chat_response, status=200, prompt="Pergunta", create_response=None):
        requests = []

        def respond(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(201, json=create_response or {"id": CONVERSATION_ID})
            return httpx.Response(status, json=chat_response)

        client = httpx.Client(transport=httpx.MockTransport(respond))
        with patch.object(self.service, "_access_token", return_value="test-access-token"), patch("knightagent.copilot_auth.httpx.Client", return_value=client):
            result = self.service.consult(prompt)
        return result, requests

    def test_consult_sends_only_one_prompt_and_uses_last_answer_not_echo(self):
        answer, requests = self._consult({"messages": [{"text": "Pergunta"}, {"text": "Resposta"}]})
        self.assertEqual(answer, "Resposta")
        self.assertEqual(str(requests[0].url), GRAPH_URL)
        self.assertEqual(json.loads(requests[0].content), {})
        self.assertEqual(str(requests[1].url), GRAPH_URL + "/" + CONVERSATION_ID + "/chat")
        self.assertEqual(json.loads(requests[1].content), {
            "message": {"text": "Pergunta"}, "locationHint": {"timeZone": "UTC"},
            "contextualResources": {"webContext": {"isWebEnabled": True}},
        })
        self.assertEqual(requests[1].extensions["timeout"]["read"], 90)
        self.assertEqual(requests[1].extensions["timeout"]["connect"], 5)

    def test_echo_or_empty_response_is_not_success(self):
        for payload in ({}, {"messages": []}, {"messages": [{"text": "Pergunta"}]},
                        {"messages": [{"text": "Pergunta"}, {"text": "Pergunta"}]},
                        {"messages": [{"text": "Pergunta"}, {"text": ""}]}):
            with self.subTest(payload=payload), self.assertRaises(CopilotError):
                self._consult(payload)

    def test_output_is_bounded(self):
        result, _ = self._consult({"messages": [{"text": "Pergunta"}, {"text": "a" * 30000}]})
        self.assertEqual(len(result), MAX_RESPONSE_CHARS)

    def test_conversation_identifier_cannot_alter_request_path(self):
        for identifier in ("../other", "https://evil.test/", None, [], 123):
            with self.subTest(identifier=identifier), self.assertRaises(CopilotError) as captured:
                self._consult({}, create_response={"id": identifier})
            self.assertEqual(captured.exception.status, "unavailable")

    def test_opaque_non_uuid_conversation_identifiers_are_supported(self):
        answer, requests = self._consult(
            {"messages": [{"text": "Pergunta"}, {"text": "Resposta"}]},
            create_response={"id": "opaque:id+base64="},
        )
        self.assertEqual(answer, "Resposta")
        self.assertTrue(str(requests[1].url).endswith("/opaque%3Aid%2Bbase64%3D/chat"))

    def test_oversized_response_rejected_before_json_decoding(self):
        with patch("knightagent.copilot_auth.MAX_RESPONSE_BYTES", 100), self.assertRaises(CopilotError) as captured:
            self._consult({"messages": [{"text": "Pergunta"}, {"text": "a" * 1000}]})
        self.assertIn("limite", str(captured.exception))

    def test_network_exception_cannot_leak_request_tokens(self):
        with patch.object(self.service, "_access_token", side_effect=httpx.ConnectError("Bearer SECRET")):
            with self.assertRaises(CopilotError) as captured:
                self.service.consult("Pergunta")
        self.assertEqual(captured.exception.status, "unavailable")
        self.assertNotIn("SECRET", str(captured.exception))

    def test_oversized_prompt_never_authenticates(self):
        with patch.object(self.service, "_access_token") as token:
            for prompt in ("", " ", "a" * 6001, None):
                with self.assertRaises(CopilotError):
                    self.service.consult(prompt)
            token.assert_not_called()

    def test_graph_errors_are_sanitized_and_meaningful(self):
        for code, expected in ((401, "session_expired"), (403, "access_denied"), (429, "unavailable"), (500, "unavailable"), (302, "unavailable")):
            with self.subTest(code=code), self.assertRaises(CopilotError) as captured:
                self._consult({"error": {"message": "SECRET TOKEN"}}, code)
            self.assertEqual(captured.exception.status, expected)
            self.assertNotIn("SECRET", str(captured.exception))

    def test_verify_access_checks_chat_before_reporting_ready(self):
        with patch.object(self.service, "consult", return_value="OK") as consult, patch.object(self.service, "status", return_value={"account": ACCOUNT["username"]}):
            result = self.service.verify_access()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(consult.call_args.args, ("Responda apenas: Conexão verificada.",))
        with patch.object(self.service, "consult", side_effect=CopilotError("Licença necessária", "access_denied")):
            self.assertEqual(self.service.verify_access()["status"], "access_denied")

    def test_auth_transport_rejects_non_microsoft_urls_and_redirects(self):
        client = Mock()
        transport = _AuthHTTP(client)
        for url in ("http://login.microsoftonline.com/", "https://evil.test/", "https://user@login.microsoftonline.com/", "https://login.microsoftonline.com:444/"):
            with self.assertRaises(CopilotError):
                transport.get(url)
        client.request.assert_not_called()
        client.request.return_value.status_code = 302
        with self.assertRaises(CopilotError):
            transport.get("https://login.microsoftonline.com/organizations")

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI is required")
    def test_dpapi_cache_is_per_registration_and_signout_is_local(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            self.service._save_cache(account_cache().serialize())
            protected = self.service._path().read_bytes()
            self.assertNotIn(ACCOUNT["username"].encode(), protected)
            self.assertFalse(protected.startswith(b"{"))
            other = CopilotService({"client_id": "a72684fd-b5f6-4e2b-a4a5-f98da5c38d6b"})
            other._save_cache(account_cache().serialize())
            with patch("knightagent.copilot_auth.httpx.Client") as client, patch("msal.PublicClientApplication") as app:
                result = self.service.logout()
                self.assertEqual(self.service.status()["status"], "disconnected")
                self.assertEqual(other.status()["status"], "authenticated")
                client.assert_not_called()
                app.assert_not_called()
            self.assertEqual(result["status"], "disconnected")


if __name__ == "__main__":
    unittest.main()
