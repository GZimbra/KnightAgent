import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from knightagent.copilot import detect_copilot, open_copilot, CopilotUnavailable


class CopilotDesktopTests(unittest.TestCase):
    @patch("knightagent.copilot.sys.platform", "win32")
    @patch("knightagent.copilot.subprocess.run")
    def test_only_installed_microsoft_apps_and_no_shell(self, run):
        app_id = "Microsoft.Copilot_8wekyb3d8bbwe!App"
        run.return_value = Mock(stdout=json.dumps(["https://copilot.microsoft.com", "evil!App", app_id]))
        self.assertEqual(detect_copilot(), app_id)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs["timeout"], 20)

    @patch("knightagent.copilot.sys.platform", "win32")
    @patch("knightagent.copilot.subprocess.run")
    def test_microsoft_365_desktop_app_supported_without_graph(self, run):
        app_id = "Microsoft.MicrosoftOfficeHub_8wekyb3d8bbwe!Microsoft.MicrosoftOfficeHub"
        run.return_value = Mock(stdout=json.dumps(app_id))
        self.assertEqual(detect_copilot(), app_id)

    @patch("knightagent.copilot.os.startfile", create=True)
    @patch("knightagent.copilot.detect_copilot", return_value="Microsoft.Copilot_8wekyb3d8bbwe!App")
    def test_open_has_no_prompt_or_files(self, detect, startfile):
        self.assertIn("Copilot aberto", open_copilot())
        startfile.assert_called_once_with("shell:AppsFolder\\Microsoft.Copilot_8wekyb3d8bbwe!App")

    @patch("knightagent.copilot.os.startfile", create=True)
    @patch("knightagent.copilot.detect_copilot", return_value=None)
    def test_missing_app_has_no_browser_fallback(self, detect, startfile):
        with self.assertRaises(CopilotUnavailable):
            open_copilot()
        startfile.assert_not_called()

    @patch("knightagent.copilot.sys.platform", "win32")
    @patch("knightagent.copilot.subprocess.run", side_effect=subprocess.TimeoutExpired("powershell", 20))
    def test_discovery_timeout_is_bounded(self, run):
        self.assertIsNone(detect_copilot())
