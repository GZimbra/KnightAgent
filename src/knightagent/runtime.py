"""Own the local Ollama server's complete lifetime, without downloads or cloud APIs."""

import ctypes
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time

import httpx

from knightagent.offline import validate_local_model
from knightagent.providers.base import ProviderError
from knightagent.providers.ollama import OllamaProvider


def _local_path(path):
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw or raw.startswith(("\\\\", "//")) or "://" in raw:
        raise ValueError("Runtime e modelos devem estar em um disco local, nunca em compartilhamentos de rede.")
    candidate = Path(os.path.abspath(os.path.expanduser(raw)))
    if os.name == "nt" and ctypes.windll.kernel32.GetDriveTypeW(str(candidate.anchor)) == 4:
        raise ValueError("Unidades de rede nao sao permitidas para o runtime ou modelos.")
    # Check each parent before following it; a local-looking junction can route
    # file operations over SMB and bypass an HTTP-only boundary.
    for part in (*reversed(candidate.parents), candidate):
        try:
            details = part.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
            raise ValueError("Links simbolicos e junctions nao sao permitidos para o runtime ou modelos.")
    return candidate


def find_ollama(config_path):
    """Prefer a portable runtime shipped beside the application."""
    root = _local_path(config_path).parent
    executable_root = Path(sys.executable).resolve().parent
    filename = "ollama.exe" if os.name == "nt" else "ollama"
    candidates = [root / "runtime" / "ollama" / filename,
                  executable_root / "runtime" / "ollama" / filename]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Ollama" / filename)
    found = shutil.which(filename)
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        candidate = _local_path(candidate)
        if candidate.is_file():
            return candidate
    raise ProviderError(
        "Runtime Ollama ausente. Disponibilize ollama.exe e suas bibliotecas em runtime/ollama "
        "junto do aplicativo, ou use uma instalacao local existente. Nenhum download sera feito."
    )


def _models_directory(config_path):
    root = _local_path(config_path).parent
    for candidate in (root / "runtime" / "ollama" / "models", root / "runtime" / "models"):
        candidate = _local_path(candidate)
        if candidate.is_dir():
            return _local_path(candidate)
    return _local_path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # SO_EXCLUSIVEADDRUSE prevents accidental Windows port sharing.
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _server_environment(home, models, port, config):
    # Do not inherit existing server, proxies, origins, cloud credentials or debug
    # settings. Preserve normal runtime/driver variables required by CPU/GPU backends.
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("OLLAMA_")
           and not key.upper().endswith(("_PROXY", "_API_KEY", "_TOKEN", "_SECRET"))
           and key.upper() not in {"ALL_PROXY", "API_KEY", "TOKEN", "SECRET"}}
    env.update({
        "HOME": str(home), "USERPROFILE": str(home),
        "OLLAMA_HOST": f"127.0.0.1:{port}", "OLLAMA_MODELS": str(models),
        "OLLAMA_NO_CLOUD": "1", "OLLAMA_NOHISTORY": "1", "OLLAMA_NOPRUNE": "1",
        "OLLAMA_KEEP_ALIVE": "-1", "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_MAX_QUEUE": "4",
        "OLLAMA_CONTEXT_LENGTH": str(config["ollama"].get("num_ctx", 8192)),
        "OLLAMA_FLASH_ATTENTION": "1", "NO_PROXY": "127.0.0.1,localhost,::1",
    })
    return env


class _WindowsJob:
    """Closing this job kills only our server and its inherited model runners."""

    def __init__(self, process):
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IOCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IOCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (not self.handle or not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                or not self.api.AssignProcessToJobObject(self.handle, int(process._handle))):
            self.close()
            raise ProviderError("Nao foi possivel vincular o Ollama ao ciclo de vida do aplicativo.")

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class OllamaRuntime:
    """Start/preload are synchronous for use in a worker; close can cancel either."""

    def __init__(self, config, config_path):
        self.config = config
        self.config_path = _local_path(config_path)
        self._process = None
        self._job = None
        self._session = None
        self._log = None
        self._log_path = None
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._started = False

    @property
    def running(self):
        return not self._stopped.is_set() and self._process is not None and self._process.poll() is None

    def _log_text(self):
        try:
            return self._log_path.read_text(encoding="utf-8", errors="replace")[-64000:]
        except (OSError, AttributeError):
            return ""

    def start(self):
        if self._started and self.running:
            return "Servidor Ollama local iniciado; recursos cloud desativados."
        if self._stopped.is_set():
            raise ProviderError("Inicializacao da IA local cancelada.")
        validate_local_model(self.config["ollama"]["model"])
        executable = find_ollama(self.config_path)
        if sys.platform == "win32":
            from knightagent.network_guard import assert_offline_firewall
            assert_offline_firewall(executable)
        models = _models_directory(self.config_path)
        port = _free_port()
        url = f"http://127.0.0.1:{port}"
        try:
            with self._lock:
                if self._stopped.is_set():
                    raise ProviderError("Inicializacao da IA local cancelada.")
                sessions = self.config_path.parent / "runtime" / "sessions"
                sessions.mkdir(parents=True, exist_ok=True)
                self._session = tempfile.TemporaryDirectory(prefix="ollama-", dir=sessions)
                home = Path(self._session.name)
                (home / ".ollama").mkdir()
                (home / ".ollama" / "server.json").write_text(json.dumps({"disable_ollama_cloud": True}), encoding="utf-8")
                self._log_path = home / "server.log"
                self._log = self._log_path.open("wb")
                kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
                self._process = subprocess.Popen(
                    [str(executable), "serve"], cwd=str(executable.parent),
                    env=_server_environment(home, models, port, self.config),
                    stdin=subprocess.DEVNULL, stdout=self._log, stderr=subprocess.STDOUT, **kwargs,
                )
                if os.name == "nt":
                    self._job = _WindowsJob(self._process)
                self.config["ollama"]["url"] = url
            deadline = time.monotonic() + min(self.config.get("timeout", 120), 45)
            with httpx.Client(timeout=httpx.Timeout(1, connect=0.5), trust_env=False, follow_redirects=False) as client:
                while time.monotonic() < deadline and not self._stopped.is_set():
                    if not self.running:
                        raise ProviderError("Ollama encerrou durante a inicializacao; confira o runtime e suas bibliotecas locais.")
                    logs = self._log_text()
                    # Require proof from OUR child's log before probing a port. An
                    # existing service (or a bind race) must never be silently reused.
                    owns_port = f"Listening on 127.0.0.1:{port}" in logs
                    cloud_disabled = "Ollama cloud disabled: true" in logs
                    if owns_port and cloud_disabled:
                        try:
                            response = client.get(url + "/api/tags")
                            data = response.json()
                            if response.status_code == 200 and isinstance(data, dict) and isinstance(data.get("models"), list) and self.running:
                                self._started = True
                                return "Servidor Ollama local iniciado; recursos cloud desativados."
                        except (httpx.HTTPError, ValueError):
                            pass
                    self._stopped.wait(0.15)
            if self._stopped.is_set():
                raise ProviderError("Inicializacao da IA local cancelada.")
            raise ProviderError(
                "Ollama nao confirmou inicializacao local com cloud desativado. "
                "Use um runtime compativel com OLLAMA_NO_CLOUD; nenhum servico externo sera reutilizado."
            )
        except Exception:
            self.close()
            raise

    def preload(self):
        if not self._started or not self.running:
            raise ProviderError("Inicie a IA local antes de carregar o modelo.")
        provider = OllamaProvider(**self.config["ollama"], timeout=self.config.get("timeout", 120))
        try:
            return provider.preload()
        finally:
            provider.close()

    def close(self):
        self._stopped.set()
        with self._lock:
            process, job = self._process, self._job
            self._process = self._job = None
            log, session = self._log, self._session
            self._log = self._session = None
        if job:
            job.close()
        if process and process.poll() is None:
            try:
                if os.name == "nt":
                    process.terminate()
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if log:
            log.close()
        if session:
            try:
                session.cleanup()
            except OSError:
                pass
