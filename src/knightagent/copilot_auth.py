"""Microsoft 365 Copilot authentication, used only by the online helper process.

The local model never receives credentials. Status and sign-out are local-only;
only explicit sign-in, verification or consultation may access Microsoft.
"""

from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx


GRAPH_URL = "https://graph.microsoft.com/beta/copilot/conversations"
SCOPES = ["https://graph.microsoft.com/" + scope for scope in (
    "Sites.Read.All", "Mail.Read", "People.Read.All",
    "OnlineMeetingTranscript.Read.All", "Chat.Read", "ChannelMessage.Read.All",
    "ExternalItem.Read.All",
)]
MAX_PROMPT_CHARS = 6000
MAX_RESPONSE_CHARS = 6000
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
LOGIN_TIMEOUT = 180


class CopilotError(RuntimeError):
    """An error with a safe user-facing message; never includes HTTP bodies."""

    def __init__(self, message, status="error"):
        super().__init__(message)
        self.status = status


def normalize_settings(settings):
    """Accept only public registration identifiers, never secrets or endpoints."""
    if not isinstance(settings, dict) or set(settings) - {"client_id", "tenant"}:
        raise ValueError("Copilot aceita somente client_id e tenant públicos.")
    client_id = settings.get("client_id", "")
    tenant = settings.get("tenant", "organizations")
    if not isinstance(client_id, str) or not isinstance(tenant, str):
        raise ValueError("Os identificadores do Copilot devem ser textos.")
    client_id, tenant = client_id.strip(), tenant.strip()
    try:
        if client_id:
            client_id = str(UUID(client_id))
        if tenant != "organizations":
            tenant = str(UUID(tenant))
    except (ValueError, AttributeError):
        raise ValueError("Use o ID de aplicativo e o ID de diretório (UUID), ou organizations.") from None
    return {"client_id": client_id, "tenant": tenant}


def _result(status, message, account=None):
    result = {"status": status, "message": message}
    if isinstance(account, str) and account:
        result["account"] = "".join(c for c in account if c.isprintable())[:254]
    return result


def _auth_error(result):
    """Translate known OAuth codes without exposing descriptions or token data."""
    result = result if isinstance(result, dict) else {}
    codes = result.get("error_codes", [])
    codes = {str(code) for code in codes} if isinstance(codes, list) else set()
    error = result.get("error")
    if codes & {"65001", "65004", "90094", "90093"} or error == "consent_required":
        return CopilotError(
            "A organização precisa autorizar as permissões do KnightAgent. Solicite consentimento ao administrador do Microsoft 365.",
            "consent_required",
        )
    if codes & {"700016", "7000218", "50011", "70011"} or error in {"invalid_client", "unauthorized_client", "invalid_scope"}:
        return CopilotError(
            "Confira o registro do aplicativo no Entra: ID, diretório, permissões delegadas e redirecionamento http://localhost para aplicativo desktop.",
            "setup_required",
        )
    if error in {"interaction_required", "login_required", "invalid_grant"}:
        return CopilotError("A sessão Microsoft precisa ser renovada. Clique em Entrar com Microsoft.", "session_expired")
    if error in {"access_denied", "authentication_canceled", "user_cancelled"}:
        return CopilotError("Entrada cancelada ou não autorizada. A sessão anterior foi preservada.", "access_denied")
    return CopilotError("Não foi possível concluir a entrada Microsoft. Tente novamente ou consulte o administrador.")


class _AuthHTTP:
    """MSAL HTTP adapter: fixed Microsoft authority, TLS and bounded requests."""

    def __init__(self, client):
        self.client = client

    def _request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "login.microsoftonline.com"
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise CopilotError("O endereço de autenticação Microsoft não foi reconhecido.", "setup_required")
        allowed = {key: value for key, value in kwargs.items() if key in {"params", "data", "json", "headers"}}
        response = self.client.request(method, url, **allowed)
        if 300 <= response.status_code < 400:
            raise CopilotError("A autenticação recebeu um redirecionamento de rede inesperado.", "unavailable")
        return response

    def get(self, url, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._request("POST", url, **kwargs)


class CopilotService:
    def __init__(self, settings):
        self.settings = normalize_settings(settings)

    def _configured(self):
        if not self.settings["client_id"]:
            raise CopilotError(
                "A conexão Microsoft precisa ser preparada uma vez pelo responsável: informe o ID público do aplicativo registrado no Entra.",
                "setup_required",
            )

    def _path(self):
        self._configured()
        if sys.platform != "win32":
            raise CopilotError("A conexão protegida com Copilot requer Windows.", "unavailable")
        root = os.environ.get("LOCALAPPDATA", "")
        if not root or not Path(root).is_absolute():
            raise CopilotError("A pasta protegida da conta Windows não está disponível.", "unavailable")
        key = hashlib.sha256((self.settings["client_id"] + ":" + self.settings["tenant"]).encode()).hexdigest()
        return Path(root) / "KnightAgent" / "Copilot" / (key + ".bin")

    @staticmethod
    def _dependencies():
        try:
            import msal
            import msal_extensions
        except ImportError:
            raise CopilotError("O componente de entrada Microsoft não está instalado nesta edição.", "unavailable") from None
        # Libraries may otherwise emit HTTP requests or identity data under a
        # host application's DEBUG logger. This module runs in a private helper.
        for name in ("msal", "msal_extensions", "httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        return msal, msal_extensions

    def _load_cache(self):
        path = self._path()
        if not path.is_file():
            return None
        _, extensions = self._dependencies()
        persistence = extensions.FilePersistenceWithDataProtection(str(path))
        return extensions.PersistedTokenCache(persistence)

    def _save_cache(self, serialized):
        path = self._path()
        _, extensions = self._dependencies()
        persistence = extensions.FilePersistenceWithDataProtection(str(path))
        with extensions.CrossPlatLock(str(path) + ".lockfile"):
            persistence.save(serialized)

    def _accounts(self, cache):
        if cache is None:
            return []
        return list(cache.search("Account"))

    @contextmanager
    def _application(self, cache):
        msal, _ = self._dependencies()
        with httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False, trust_env=False) as client:
            app = msal.PublicClientApplication(
                self.settings["client_id"],
                authority="https://login.microsoftonline.com/" + self.settings["tenant"],
                token_cache=cache,
                http_client=_AuthHTTP(client),
                instance_discovery=False,
                enable_pii_log=False,
                app_name="KnightAgent",
            )
            yield app

    @staticmethod
    def _failure(error):
        if isinstance(error, CopilotError):
            return _result(error.status, str(error))
        if isinstance(error, (httpx.HTTPError, TimeoutError)):
            return _result("unavailable", "Não foi possível acessar a Microsoft. Verifique a conexão e tente novamente.")
        return _result("error", "Não foi possível acessar a sessão protegida do Copilot. Tente conectar novamente.")

    def status(self):
        """Read local cached account metadata only; do not refresh any tokens."""
        try:
            accounts = self._accounts(self._load_cache())
            if not accounts:
                return _result("disconnected", "Nenhuma conta Microsoft conectada neste Windows.")
            return _result(
                "authenticated", "Conta salva. Use Verificar acesso para confirmar a licença e as permissões.",
                accounts[0].get("username"),
            )
        except Exception as error:
            return self._failure(error)

    def login(self):
        """Browser authorization-code flow with MSAL's PKCE; never a password UI."""
        try:
            self._configured()
            self._path()  # Check encrypted persistence availability before login.
            msal, _ = self._dependencies()
            # A cancelled account switch must leave the previous session intact.
            cache = msal.SerializableTokenCache()
            with self._application(cache) as app:
                response = app.acquire_token_interactive(
                    scopes=SCOPES, prompt="select_account", timeout=LOGIN_TIMEOUT,
                )
            if not isinstance(response, dict) or not response.get("access_token"):
                raise _auth_error(response)
            accounts = self._accounts(cache)
            if not accounts:
                raise CopilotError("A entrada não criou uma sessão válida. Tente novamente.")
            self._save_cache(cache.serialize())
            return _result(
                "authenticated", "Conta conectada. Verifique o acesso para confirmar a licença Microsoft 365 Copilot.",
                accounts[0].get("username"),
            )
        except Exception as error:
            return self._failure(error)

    def logout(self):
        """Forget only this registration's local cache, leaving browser SSO intact."""
        try:
            path = self._path()
            if path.is_file():
                self._save_cache("{}")
            return _result("disconnected", "Conta removida deste aplicativo. A sessão do navegador permanece como está.")
        except Exception as error:
            return self._failure(error)

    def _access_token(self):
        cache = self._load_cache()
        accounts = self._accounts(cache)
        if not accounts:
            raise CopilotError("Entre com sua conta Microsoft para usar o Copilot.", "disconnected")
        with self._application(cache) as app:
            response = app.acquire_token_silent_with_error(SCOPES, account=accounts[0])
        if not isinstance(response, dict) or not response.get("access_token"):
            if response is None:
                raise CopilotError("A sessão Microsoft expirou. Clique em Entrar com Microsoft.", "session_expired")
            raise _auth_error(response)
        return response["access_token"]

    @staticmethod
    def _post(client, url, body, token, timeout):
        try:
            with client.stream(
                "POST", url, json=body, headers={"Authorization": "Bearer " + token},
                timeout=httpx.Timeout(timeout, connect=5),
            ) as response:
                if response.status_code == 401:
                    raise CopilotError("A sessão Microsoft precisa ser renovada. Entre novamente.", "session_expired")
                if response.status_code == 403:
                    raise CopilotError(
                        "A Microsoft negou o acesso. Confirme a licença Microsoft 365 Copilot e o consentimento do administrador para as permissões.",
                        "access_denied",
                    )
                if response.status_code == 429:
                    raise CopilotError("O Copilot atingiu o limite temporário de consultas. Tente novamente mais tarde.", "unavailable")
                if response.status_code >= 500:
                    raise CopilotError("O serviço Copilot está temporariamente indisponível.", "unavailable")
                if response.status_code not in (200, 201):
                    raise CopilotError("A Microsoft não aceitou a consulta. Confira a configuração e a disponibilidade da API de Copilot.", "unavailable")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise CopilotError("O Copilot retornou uma resposta acima do limite permitido.", "unavailable")
                payload = json.loads(data)
                if not isinstance(payload, dict):
                    raise ValueError("Invalid Graph envelope")
                return payload
        except CopilotError:
            raise
        except (httpx.HTTPError, TimeoutError):
            raise CopilotError("Não foi possível acessar o Copilot. Verifique a conexão e tente novamente.", "unavailable") from None
        except (ValueError, UnicodeError):
            raise CopilotError("O Copilot retornou uma resposta inválida.", "unavailable") from None

    def consult(self, prompt):
        """One fresh conversation, containing only the explicitly supplied prompt."""
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
            raise CopilotError("A consulta ao Copilot deve conter entre 1 e 6000 caracteres.")
        prompt = prompt.strip()
        try:
            token = self._access_token()
            with httpx.Client(follow_redirects=False, trust_env=False) as client:
                conversation = self._post(client, GRAPH_URL, {}, token, 30)
                conversation_id = conversation.get("id")
                # Graph defines this property as an opaque String, not a GUID.
                # Accept common opaque IDs while forbidding paths and dot-only
                # segments; encode reserved punctuation as one path parameter.
                if (not isinstance(conversation_id, str)
                        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.~+=:-]{0,255}", conversation_id)):
                    raise CopilotError("O Copilot não retornou uma conversa válida.", "unavailable")
                payload = self._post(
                    client, GRAPH_URL + "/" + quote(conversation_id, safe="") + "/chat",
                    {"message": {"text": prompt}, "locationHint": {"timeZone": "UTC"},
                     "contextualResources": {"webContext": {"isWebEnabled": True}}},
                    token, 90,
                )
            messages = payload.get("messages")
            # The documented schema returns request and assistant messages with
            # the same OData type; the assistant reply is last. Never echo the
            # request as a successful Copilot response.
            if not isinstance(messages, list) or len(messages) < 2:
                raise CopilotError("O Copilot não retornou uma resposta de texto.", "unavailable")
            last = messages[-1]
            answer = last.get("text") if isinstance(last, dict) else None
            if not isinstance(answer, str) or not answer.strip() or answer.strip() == prompt:
                raise CopilotError("O Copilot não retornou uma resposta de texto.", "unavailable")
            return answer.strip()[:MAX_RESPONSE_CHARS]
        except CopilotError:
            raise
        except Exception as error:
            failure = self._failure(error)
            raise CopilotError(failure["message"], failure["status"]) from None

    def verify_access(self):
        try:
            self.consult("Responda apenas: Conexão verificada.")
            account = self.status().get("account")
            return _result("ready", "Acesso ao Microsoft 365 Copilot verificado. O auxílio em segundo plano está disponível.", account)
        except Exception as error:
            return self._failure(error)
