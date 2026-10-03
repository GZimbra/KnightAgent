import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from knightagent.network_guard import assert_offline_firewall, REMOTE_RANGES


class NetworkGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.executable = Path(temporary.name) / "ollama.exe"
        self.executable.touch()
        self.runner = self.executable.parent / "lib" / "llama-server.exe"
        self.runner.parent.mkdir()
        self.runner.touch()
        self.rules = [dict(program=str(path.resolve()), addresses=list(REMOTE_RANGES),
                           protocol="Any", service="Any", interfaces=["Any"],
                           localAddresses=["Any"], localPorts=["Any"], remotePorts=["Any"],
                           interfaceType="Any", primaryStatus="OK", enforcementStatus="Full")
                      for path in (self.executable, self.runner)]

    def check(self, profiles=None, rules=None):
        result = Mock(stdout=json.dumps({"profiles": profiles if profiles is not None else [1, 1, 1],
                                       "rules": self.rules if rules is None else rules}))
        with patch("knightagent.network_guard.sys.platform", "win32"), patch(
                "knightagent.network_guard.subprocess.run", return_value=result):
            assert_offline_firewall(self.executable)

    def test_covers_all_runtime_executables(self):
        self.check()

    def test_enforced_and_inactive_network_profiles_are_normal(self):
        for rule in self.rules:
            rule["enforcementStatus"] = "ProfileInactive Enforced"
        self.check()

    def test_missing_runner_rule_fails_closed(self):
        with self.assertRaises(RuntimeError):
            self.check(rules=self.rules[:1])

    def test_any_disabled_profile_fails_closed(self):
        with self.assertRaises(RuntimeError):
            self.check(profiles=[1, 0, 1])

    def test_rule_limited_to_one_protocol_fails_closed(self):
        self.rules[0]["protocol"] = "TCP"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_ipv4_only_rule_fails_closed(self):
        self.rules[0]["addresses"] = self.rules[0]["addresses"][:1]
        with self.assertRaises(RuntimeError):
            self.check()

    def test_restricted_ports_or_interfaces_fail_closed(self):
        for field, value in (("localPorts", ["443"]), ("remotePorts", ["443"]),
                             ("localAddresses", ["192.168.1.1"]), ("interfaceType", "Wireless"),
                             ("enforcementStatus", "LocalFirewallRulesDisallowed")):
            with self.subTest(field=field):
                previous = self.rules[0][field]
                self.rules[0][field] = value
                with self.assertRaises(RuntimeError):
                    self.check()
                self.rules[0][field] = previous

    def test_packaged_application_also_requires_rule(self):
        with patch("knightagent.network_guard.sys.frozen", True, create=True):
            with self.assertRaises(RuntimeError):
                self.check()
