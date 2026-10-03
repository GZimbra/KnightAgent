"""Local IPC to the isolated Microsoft account component. No HTTP in the desktop."""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from uuid import UUID


OPERATIONS = {"status", "login", "logout", "verify_access", "consult"}
STATUSES = {"setup_required", "disconnected", "authenticated", "ready",
            "consent_required", "session_expired", "access_denied", "unavailable", "error"}
MAX_PROMPT_CHARS = 6000
MAX_RESPONSE_CHARS = 6000


class CopilotClientError(RuntimeError):
    pass


def public_settings(settings):
    if not isinstance(settings, dict):
        raise CopilotClientError("Configuração Microsoft Entra inválida.")
    client_id = settings.get("client_id", "")
    tenant = settings.get("tenant", "organizations")
    try:
        return {"client_id": str(UUID(client_id.strip())) if client_id.strip() else "",
                "tenant": "organizations" if tenant.strip() == "organizations" else str(UUID(tenant.strip()))}
    except (ValueError, AttributeError):
        raise CopilotClientError("Configuração Microsoft Entra inválida.") from None


class CopilotClient:
    """One bounded helper operation at a time; closing cancels our own child only."""

    def __init__(self, config_path, settings):
        self.config_path = Path(config_path).resolve()
        self.settings = public_settings(settings)
        self._operation = threading.Lock()
        self._state = threading.Lock()
        self._closed = threading.Event()
        self._process = None

    def _command(self):
        if getattr(sys, "frozen", False):
            # A sibling process has internet access; the main executable stays blocked.
            helper = Path(sys.executable).resolve().with_name("KnightAgentCopilot.exe")
            if not helper.is_file():
                raise CopilotClientError("Componente de conta Microsoft ausente. Mantenha KnightAgentCopilot.exe na pasta do aplicativo.")
            return [str(helper)]
        # Ignore the configured workspace and PYTHONPATH when importing the
        # network-enabled helper. The installed application owns this module.
        return [sys.executable, "-I", "-u", "-m", "knightagent.copilot_helper"]

    def _request(self, operation, prompt=None):
        if operation not in OPERATIONS:
            raise CopilotClientError("Operação Copilot inválida.")
        if self._closed.is_set():
            raise CopilotClientError("Operação Copilot cancelada.")
        if not self.settings["client_id"]:
            return {"status": "setup_required", "message":
                    "A TI precisa registrar o KnightAgent no Microsoft Entra e informar o ID do aplicativo uma única vez. Depois, cada usuário entra com sua própria conta."}
        request = {"version": 1, "operation": operation, "settings": self.settings}
        if prompt is not None:
            if operation != "consult" or not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
                raise CopilotClientError("Consulta Copilot vazia ou acima do limite de 6.000 caracteres.")
            request["prompt"] = prompt
        elif operation == "consult":
            raise CopilotClientError("Consulta Copilot vazia ou acima do limite de 6.000 caracteres.")
        timeout = {"login": 240, "consult": 125, "verify_access": 125}.get(operation, 30)
        process = None
        with self._operation:
            try:
                with self._state:
                    if self._closed.is_set():
                        raise CopilotClientError("Operação Copilot cancelada.")
                    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
                    process = subprocess.Popen(self._command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                               stderr=subprocess.DEVNULL, cwd=str(self.config_path.parent), **kwargs)
                    self._process = process
                output, _ = process.communicate(json.dumps(request, ensure_ascii=False).encode("utf-8"), timeout=timeout)
                if self._closed.is_set():
                    raise CopilotClientError("Operação Copilot cancelada.")
                if process.returncode != 0 or len(output) > 100_000:
                    raise CopilotClientError("O componente Copilot não concluiu a operação. Tente novamente nas configurações.")
                response = json.loads(output.decode("utf-8"))
                if (not isinstance(response, dict) or type(response.get("version")) is not int
                        or response.get("version") != 1 or set(response) - {"version", "error", "result"}):
                    raise ValueError()
                if response.get("error"):
                    # The helper's exception text is never forwarded to the UI.
                    raise CopilotClientError("Auxílio do Copilot indisponível. Verifique a conta, a licença e a autorização da empresa nas configurações.")
                result = response.get("result")
                if operation == "consult":
                    if not isinstance(result, str) or not result.strip() or len(result) > MAX_RESPONSE_CHARS:
                        raise ValueError()
                    return result
                if (not isinstance(result, dict) or not isinstance(result.get("status"), str)
                        or result["status"] not in STATUSES
                        or any(not isinstance(result[key], str) for key in ("message", "account") if key in result)):
                    raise ValueError()
                return {key: result[key][:1200] for key in ("status", "message", "account") if key in result}
            except subprocess.TimeoutExpired:
                raise CopilotClientError("A operação Copilot excedeu o tempo disponível. O login pode ser tentado novamente.") from None
            except (OSError, ValueError, UnicodeError):
                raise CopilotClientError("Não foi possível iniciar ou interpretar a resposta do componente Copilot.") from None
            finally:
                with self._state:
                    if self._process is process:
                        self._process = None
                if process is not None:
                    self._reap(process)
                    for stream in (process.stdin, process.stdout):
                        if stream is not None:
                            try:
                                stream.close()
                            except OSError:
                                pass

    @staticmethod
    def _reap(process):
        """Kill/reap only our helper, without an unbounded communicate retry."""
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def status(self):
        return self._request("status")

    def login(self):
        return self._request("login")

    def logout(self):
        return self._request("logout")

    def verify_access(self):
        return self._request("verify_access")

    def consult(self, prompt):
        result = self._request("consult", prompt)
        if not isinstance(result, str):
            raise CopilotClientError("Configure o aplicativo Microsoft Entra e entre com sua conta para usar o Copilot.")
        return result

    def close(self):
        self._closed.set()
        with self._state:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                self._reap(process)
