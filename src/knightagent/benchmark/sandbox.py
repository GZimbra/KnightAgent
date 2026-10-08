"""Run generated code in a temporary WSL chroot without host mounts or network."""

import json
import os
from pathlib import Path
import subprocess


class SandboxUnavailable(RuntimeError):
    pass


WORKER = Path(__file__).with_name("sandbox_worker.py")
SCRIPT = Path(__file__).with_name("sandbox_linux.sh")


def _wsl_path(path):
    path = Path(path).resolve()
    if path.drive and len(path.drive) == 2 and path.drive[1] == ":":
        return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]
    raise SandboxUnavailable("WSL sandbox requires a local Windows drive path")


def execute(payload, *, distro, memory_mb, cpu_seconds, wall_seconds, directory):
    if not (isinstance(distro, str) and distro and type(memory_mb) is int and 128 <= memory_mb <= 4096
            and type(cpu_seconds) is int and 1 <= cpu_seconds <= 30
            and type(wall_seconds) is int and cpu_seconds <= wall_seconds <= 120):
        raise ValueError("Invalid sandbox resource configuration")
    wsl = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wsl.exe"
    if not wsl.is_file():
        raise SandboxUnavailable("WSL executable unavailable")
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
    cmd = [str(wsl), "-d", distro, "-u", "root", "--", "bash", _wsl_path(SCRIPT),
           _wsl_path(WORKER), str(memory_mb * 1024 * 1024), str(cpu_seconds), str(wall_seconds)]
    try:
        result = subprocess.run(cmd, input=json.dumps(payload), text=True, capture_output=True,
                                cwd=directory, env=env, timeout=wall_seconds + 30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SandboxUnavailable(f"WSL sandbox unavailable: {type(error).__name__}") from None
    if result.returncode in (124, 137, -9):
        return {"error": "Sandbox wall timeout"}
    try:
        data = json.loads(result.stdout)
    except ValueError:
        if result.returncode and any(marker in result.stderr for marker in ("unshare:", "mount:", "chroot:")):
            raise SandboxUnavailable("WSL isolation primitives unavailable") from None
        if result.returncode:
            return {"error": "Sandbox process stopped under CPU, memory or process limit"}
        raise SandboxUnavailable("WSL sandbox returned no result") from None
    if not isinstance(data, dict) or set(data) - {"results", "error"}:
        raise SandboxUnavailable("WSL sandbox returned an invalid result")
    return data
