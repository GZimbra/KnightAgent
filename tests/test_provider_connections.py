import json
import unittest
from unittest.mock import patch

import httpx

from knightagent.offline import is_local_model, validate_local_model, validate_local_url
from knightagent.providers.base import ProviderError
from knightagent.providers.ollama import OllamaProvider


class ProviderConnectionTests(unittest.TestCase):
    def provider(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
        self.addCleanup(client.close)
        return OllamaProvider("test", client=client)

    def test_loopback_origin_validation_is_strict_and_avoids_dns(self):
        self.assertEqual(validate_local_url("http://localhost:12345/"), "http://127.0.0.1:12345")
        self.assertEqual(validate_local_url("http://[::1]:11434"), "http://[::1]:11434")
        for url in ("https://127.0.0.1", "http://127.0.0.1:0", "http://0.0.0.0:11434",
                    "http://localhost:65536", "http://localhost:", "http://localhost/api",
                    "http://localhost?cloud=1", "http://localhost#fragment", "http://user@localhost",
                    "http://127.0.0.1.evil.test", "http://localhost\n", "http://localhost\\evil.test"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_local_url(url)

    def test_remote_model_names_are_rejected_before_client_creation(self):
        for name in ("qwen:cloud", "gpt-oss:120b-cloud", "qwen-cloud:latest", "https://ollama.com/m",
                     "registry.ollama.ai/library/qwen:7b", "../test", "x//y", "model\n"):
            with self.subTest(model=name), patch("knightagent.providers.base.httpx.Client") as factory:
                with self.assertRaises(ValueError):
                    OllamaProvider(name)
                factory.assert_not_called()
        self.assertEqual(validate_local_model("team/model:7b-q4_0"), "team/model:7b-q4_0")

    def test_cloud_alias_inventory_is_rejected_before_show_or_generation(self):
        for details in ({"remote_host": "https://ollama.com"}, {"remote_model": "remote"},
                        {"details": {"remote_host": "https://ollama.com"}}):
            requests = []
            def handler(request):
                requests.append(request.url.path)
                return httpx.Response(200, json={"models": [{"name": "test", **details}]})
            with self.subTest(details=details), self.assertRaisesRegex(ProviderError, "remoto"):
                self.provider(handler).chat([{"role": "user", "content": "PRIVATE"}], [])
            self.assertEqual(requests, ["/api/tags"])

    def test_show_remote_metadata_rejected_before_generation(self):
        requests = []
        def handler(request):
            requests.append(request.url.path)
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "test"}]})
            return httpx.Response(200, json={"capabilities": ["tools"], "remote_model": "cloud-target"})
        with self.assertRaisesRegex(ProviderError, "remoto"):
            self.provider(handler).chat([{"role": "user", "content": "PRIVATE"}], [])
        self.assertEqual(requests, ["/api/tags", "/api/show"])

    def test_missing_or_malformed_inventory_never_pulls_models(self):
        for data in ({"models": []}, {"models": [{"name": "other"}]}, {"models": None}, {"models": {}}):
            requests = []
            def handler(request):
                requests.append(request.url.path)
                return httpx.Response(200, json=data)
            with self.subTest(data=data), self.assertRaises(ProviderError):
                self.provider(handler).chat([], [])
            self.assertEqual(requests, ["/api/tags"])

    def test_preload_sends_no_conversation_or_prompt_and_keeps_model_loaded(self):
        calls = []
        def handler(request):
            calls.append(request.url.path)
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "test"}]})
            if request.url.path == "/api/show":
                return httpx.Response(200, json={"capabilities": ["tools"]})
            body = json.loads(request.content)
            self.assertEqual(body["prompt"], "")
            self.assertEqual(body["keep_alive"], -1)
            self.assertNotIn("messages", body)
            return httpx.Response(200, json={"done": True})
        self.assertIn("pronta", self.provider(handler).preload())
        self.assertEqual(calls, ["/api/tags", "/api/show", "/api/generate"])

    def test_redirect_is_not_followed_even_with_injected_client(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(302, headers={"Location": "https://other.invalid/PRIVATE"})
        with self.assertRaisesRegex(ProviderError, "redirecionamento"):
            self.provider(handler).test_connection()
        self.assertEqual(len(requests), 1)

    def test_http_boundary_disallows_remote_and_management_endpoints(self):
        provider = self.provider(lambda request: self.fail("Network must not be called"))
        for endpoint in ("/api/pull", "/api/push", "/api/web_search", "/api/chat?remote=1", "/v1/responses"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ProviderError):
                provider.post(provider.url + endpoint, json={})
        with self.assertRaises(ValueError):
            provider.post("https://ollama.com/api/chat", json={})

    def test_create_only_accepts_local_profile_body(self):
        provider = self.provider(lambda request: self.fail("Network must not be called"))
        for body in ({"model": "new", "from": "test:cloud"},
                     {"model": "new", "from": "test", "remote_host": "https://ollama.com"},
                     {"model": "new", "from": "test", "files": {"url": "https://remote"}},
                     {"model": "new", "from": "test", "stream": True}):
            with self.subTest(body=body), self.assertRaises((ValueError, ProviderError)):
                provider.post(provider.url + "/api/create", json=body)

    def test_bad_json_is_rejected_without_exposing_content(self):
        for response in (httpx.Response(200, json=[]), httpx.Response(200, text="PRIVATE")):
            with self.subTest(response=response), self.assertRaisesRegex(ProviderError, "JSON") as raised:
                self.provider(lambda request: response).test_connection()
            self.assertNotIn("PRIVATE", str(raised.exception))

    def test_model_inventory_filter_rejects_remote_metadata(self):
        self.assertTrue(is_local_model({"name": "local:7b"}))
        self.assertFalse(is_local_model({"name": "local:cloud"}))
        self.assertFalse(is_local_model({"name": "local", "remote_host": "https://ollama.com"}))
        self.assertFalse(is_local_model({"name": "local", "remote_model": "external"}))


if __name__ == "__main__":
    unittest.main()
