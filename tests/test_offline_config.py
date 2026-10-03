import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from knightagent.config.settings import build_provider, build_providers, load


class OfflineConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "config.yaml"

    def config(self, extra=None):
        data = {"ollama": {"model": "local:7b"}, **(extra or {})}
        self.path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return load(self.path)

    def test_legacy_profiles_and_providers_are_removed_without_credential_reads(self):
        legacy = {
            "user": {"name": "Private", "email": "private@example.com"},
            "providers": {"openai": {"enabled": True, "model": "remote"}, "copilot": {"enabled": True}},
            "roles": {"planner": "openai", "executor": "auto", "reviewer": "copilot"},
        }
        with patch("knightagent.config.settings.credential") as credentials:
            config = self.config(legacy)
            providers, roles = build_providers(config)
        self.addCleanup(providers["ollama"].close)
        self.assertNotIn("user", config)
        self.assertNotIn("providers", config)
        self.assertEqual(config["complementary"], {"copilot": False, "mode": "account", "client_id": "", "tenant": "organizations"})
        self.assertEqual(set(providers), {"ollama"})
        self.assertEqual(set(roles.values()), {"ollama"})
        credentials.assert_not_called()

    def test_complementary_only_allows_explicit_copilot_boolean(self):
        self.assertTrue(self.config({"complementary": {"copilot": True, "mode": "account"}})["complementary"]["copilot"])
        # The old checkbox authorized manual copy/paste, not automatic requests.
        self.assertFalse(self.config({"complementary": {"copilot": True}})["complementary"]["copilot"])
        for value in ({"openai": True}, {"copilot": "yes"}, [], True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.config({"complementary": value})

    def test_copilot_registration_accepts_public_ids_only(self):
        identifier = "9705a654-ef61-4553-ad87-cd7f6c803759"
        valid = {"copilot": True, "mode": "account", "client_id": identifier, "tenant": identifier}
        self.assertEqual(self.config({"complementary": valid})["complementary"], valid)
        for extra in ({"mode": "desktop"}, {"client_id": "bad"}, {"tenant": "common"},
                      {"client_secret": "never-store"}, {"token": "never-store"}, {"tenant": None}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.config({"complementary": {**valid, **extra}})

    def test_direct_external_build_and_role_assignment_are_rejected(self):
        config = self.config()
        for name in ("openai", "anthropic", "gemini", "copilot"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_provider(config, name)
        config["roles"]["planner"] = "copilot"
        with self.assertRaises(ValueError):
            build_providers(config)

    def test_remote_url_and_cloud_models_rejected_when_loading(self):
        for local in ({"model": "model:cloud"}, {"model": "model", "url": "http://192.168.1.10:11434"},
                      {"model": "model", "url": "http://localhost?remote=true"}):
            with self.subTest(local=local), self.assertRaises(ValueError):
                self.config({"ollama": local})

    def test_medium_defaults_keep_model_loaded_for_session(self):
        config = self.config()
        self.assertEqual(config["performance"]["level"], "medio")
        self.assertEqual(config["ollama"]["num_ctx"], 8192)
        self.assertEqual(config["ollama"]["keep_alive"], "-1")

    def test_legacy_disabled_knowledge_is_reenabled_for_local_grounding(self):
        config = self.config({"knowledge": {"enabled": False, "max_chars": 3000}})
        self.assertEqual(config["knowledge"], {"enabled": True, "max_chars": 3000})
