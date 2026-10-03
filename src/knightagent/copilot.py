"""Explicit handoff to the installed Windows Copilot app; no network client."""

import json
import os
import re
import subprocess
import sys


class CopilotUnavailable(RuntimeError):
    pass


def detect_copilot():
    """Discover installed Microsoft Copilot desktop apps, never a web fallback."""
    if sys.platform != "win32":
        return None
    command = (
        "$ErrorActionPreference='Stop'; "
        "Get-AppxPackage | Where-Object { $_.Name -in @('Microsoft.Copilot', 'Microsoft.MicrosoftOfficeHub') } | ForEach-Object { "
        "$package=$_; $manifest=Get-AppxPackageManifest -Package $package; "
        "$manifest.Package.Applications.Application | ForEach-Object { "
        "$package.PackageFamilyName + '!' + $_.Id } } | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                          "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
             "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True,
        )
        data = json.loads(result.stdout.strip().lstrip("\ufeff")) if result.stdout.strip() else []
        candidates = [data] if isinstance(data, str) else data
        if isinstance(candidates, list):
            return next((item for item in candidates if isinstance(item, str) and
                         re.fullmatch(r"Microsoft\.(?:Copilot|MicrosoftOfficeHub)_[A-Za-z0-9]+![A-Za-z0-9_.-]+", item)), None)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def open_copilot():
    app_id = detect_copilot()
    if not app_id:
        raise CopilotUnavailable("O aplicativo Microsoft Copilot não foi encontrado neste Windows.")
    try:
        os.startfile("shell:AppsFolder\\" + app_id)
    except OSError as error:
        raise CopilotUnavailable("Não foi possível abrir o aplicativo Microsoft Copilot.") from error
    return "Copilot aberto. Cole somente o texto que deseja compartilhar."
