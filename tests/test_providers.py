import json
import unittest

import httpx

from knightagent.providers.ollama import OllamaProvider
from knightagent.providers.external import OpenAIProvider, AnthropicProvider, GeminiProvider, CopilotProvider
from knightagent.providers.base import ProviderError
from knightagent.tools.files import DEFINITIONS


class ProviderTests(unittest.TestCase):
    def client(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return client

    def test_ollama_native(self):
        def handle(request):
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "test:latest"}]})
            body = json.loads(request.content)
            if request.url.path == "/api/show":
                return httpx.Response(200, json={"capabilities": ["tools"]})
            self.assertIn("tools", body)
            self.assertNotIn("format", body)
            self.assertEqual(body["options"]["num_predict"], 1024)
            self.assertEqual(body["keep_alive"], -1)
            return httpx.Response(200, json={"message": {"content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "x"}}}]}})
        provider = OllamaProvider("test", num_predict=1024, client=self.client(handle))
        self.assertEqual(provider.chat([], DEFINITIONS).calls[0].arguments, {"path": "x"})

    def test_ollama_json_fallback(self):
        def handle(request):
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "test"}]})
            body = json.loads(request.content)
            if request.url.path == "/api/show":
                return httpx.Response(200, json={"capabilities": ["completion"]})
            self.assertIn("format", body)
            self.assertNotIn("tools", body)
            return httpx.Response(200, json={"message": {"content": '{"content":"feito","tool_calls":[]}'}})
        self.assertEqual(OllamaProvider("test", client=self.client(handle)).chat([], DEFINITIONS).content, "feito")

    def test_ollama_connection_timeout_missing(self):
        for exc, expected in ((httpx.ConnectError("secret"), "inacessivel"), (httpx.ReadTimeout("secret"), "timeout"), (None, "modelo ausente")):
            def handle(request):
                if exc:
                    raise exc
                return httpx.Response(404, json={"error": "secret"})
            with self.subTest(expected=expected), self.assertRaisesRegex(ProviderError, expected) as raised:
                OllamaProvider("test", client=self.client(handle)).chat([], [])
            self.assertNotIn("secret", str(raised.exception))

    def test_retired_adapters_reject_before_network_client_creation(self):
        for cls in (OpenAIProvider, AnthropicProvider, GeminiProvider, CopilotProvider):
            with self.subTest(provider=cls), self.assertRaisesRegex(ProviderError, "desabilitadas"):
                cls("test", key="SECRET", client=self.client(lambda request: self.fail("No network permitted")))

    def test_remote_ollama_blocked(self):
        with self.assertRaises(ValueError):
            OllamaProvider("test", url="http://remote.example:11434")
