"""Fail closed if the private Windows runtime lacks effective egress rules."""

import json
import os
from pathlib import Path
import subprocess
import sys

REMOTE_RANGES = {
    "0.0.0.0-126.255.255.255", "128.0.0.0-255.255.255.255",
    "::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
}


def assert_offline_firewall(executable):
    if sys.platform != "win32":
        raise RuntimeError("O isolamento de rede desta edição requer Windows com Firewall ativo.")
    executable = Path(executable).resolve()
    # Only an application-owned runtime can receive these per-program policies.
    expected = {str(executable).lower()}
    expected.update(str(path.resolve()).lower() for path in executable.parent.rglob("*.exe"))
    if getattr(sys, "frozen", False):
        expected.add(str(Path(sys.executable).resolve()).lower())
    script = (
        "$ErrorActionPreference='Stop'; "
        "$profiles=@(Get-NetFirewallProfile -PolicyStore ActiveStore | Select-Object -ExpandProperty Enabled); "
        "$rules=@(Get-NetFirewallRule -PolicyStore ActiveStore -Group 'KnightAgent Offline' | "
        "Where-Object { $_.Enabled -eq 'True' -and $_.Direction -eq 'Outbound' -and $_.Action -eq 'Block' -and $_.Profile -eq 'Any' } | "
        "ForEach-Object { $rule=$_; [pscustomobject]@{ program=($rule | Get-NetFirewallApplicationFilter).Program; "
        "addresses=@(($rule | Get-NetFirewallAddressFilter).RemoteAddress); "
        "localAddresses=@(($rule | Get-NetFirewallAddressFilter).LocalAddress); "
        "protocol=($rule | Get-NetFirewallPortFilter).Protocol; "
        "localPorts=@(($rule | Get-NetFirewallPortFilter).LocalPort); "
        "remotePorts=@(($rule | Get-NetFirewallPortFilter).RemotePort); "
        "interfaceType=[string]($rule | Get-NetFirewallInterfaceTypeFilter).InterfaceType; "
        "primaryStatus=[string]$rule.PrimaryStatus; enforcementStatus=[string]$rule.EnforcementStatus; "
        "service=($rule | Get-NetFirewallServiceFilter).Service; "
        "interfaces=@(($rule | Get-NetFirewallInterfaceFilter).InterfaceAlias) } }); "
        "@{profiles=$profiles;rules=$rules} | ConvertTo-Json -Depth 5 -Compress"
    )
    try:
        result = subprocess.run(
            [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
             "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        state = json.loads(result.stdout.strip().lstrip("\ufeff"))
        profiles = state.get("profiles", [])
        if len(profiles) != 3 or not all(value in (True, 1, "True") for value in profiles):
            raise ValueError("Firewall desativado")
        covered = set()
        for rule in state.get("rules", []):
            enforcement = set(str(rule.get("enforcementStatus", "")).split())
            if (set(rule.get("addresses", [])) == REMOTE_RANGES
                    and str(rule.get("protocol")) in {"Any", "256"}
                    and rule.get("localAddresses") == ["Any"]
                    and rule.get("localPorts") == ["Any"]
                    and rule.get("remotePorts") == ["Any"]
                    and rule.get("interfaceType") == "Any"
                    and rule.get("primaryStatus") == "OK"
                    and enforcement and enforcement <= {"Full", "Enforced", "ProfileInactive"}
                    and rule.get("service") == "Any"
                    and rule.get("interfaces") == ["Any"]):
                covered.add(str(rule.get("program", "")).lower())
        if not expected <= covered:
            raise ValueError("Regras ausentes ou incompletas")
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        raise RuntimeError(
            "IA não iniciada: bloqueio de rede não confirmado. Execute scripts/configure-offline-firewall.ps1 "
            "como Administrador e mantenha o Firewall do Windows ativo."
        ) from error
