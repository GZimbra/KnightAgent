"""Restricted stdio entry point for Microsoft's online account/Copilot component."""

import json
import os
import sys
import threading


def _watch_parent(handle, wait, close):
    """Stop this online child when its onefile bootloader is cancelled."""
    try:
        while wait(handle, 1000) == 258:  # WAIT_TIMEOUT
            pass
        # Both a terminated parent and a failed wait must stop this helper. No
        # process-tree termination: the user's Microsoft browser stays open.
        os._exit(1)
    except Exception:
        os._exit(1)
    finally:
        close(handle)


def _start_parent_watchdog():
    """A onefile bootloader and its Python child have distinct Windows PIDs."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    # SYNCHRONIZE only; this handle cannot kill or inspect any parent process.
    handle = kernel.OpenProcess(0x00100000, False, os.getppid())
    if not handle:
        raise RuntimeError("Parent lifecycle unavailable")
    try:
        threading.Thread(
            target=_watch_parent,
            args=(handle, kernel.WaitForSingleObject, kernel.CloseHandle),
            daemon=True, name="copilot-parent-watchdog",
        ).start()
    except Exception:
        kernel.CloseHandle(handle)
        raise


def dispatch(request):
    if (not isinstance(request, dict) or type(request.get("version")) is not int or request.get("version") != 1
            or set(request) - {"version", "operation", "settings", "prompt"}):
        raise ValueError("Invalid protocol")
    operation = request.get("operation")
    if not isinstance(operation, str) or operation not in {"status", "login", "logout", "verify_access", "consult"}:
        raise ValueError("Unknown operation")
    if operation == "consult":
        prompt = request.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 6000:
            raise ValueError("Invalid prompt")
    elif "prompt" in request:
        raise ValueError("Unexpected prompt")
    from knightagent.copilot_auth import CopilotService
    service = CopilotService(request.get("settings", {}))
    if operation == "consult":
        return service.consult(prompt)
    return getattr(service, operation)()


def main():
    try:
        _start_parent_watchdog()
        data = sys.stdin.buffer.read(64_001)
        if len(data) > 64_000:
            raise ValueError("IPC input limit exceeded")
        result = dispatch(json.loads(data.decode("utf-8")))
        response = {"version": 1, "result": result}
    except Exception:
        response = {"version": 1, "error": "copilot_unavailable"}
    sys.stdout.buffer.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
