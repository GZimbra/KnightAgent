from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from knightagent.offline import validate_local_model, validate_local_url


class ProviderError(RuntimeError):
    pass


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResponse:
    content: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)


class LLMProvider(ABC):
    external = False
    supports_tools = True

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict]) -> ChatResponse:
        """Recebe historico textual normalizado e definicoes de ferramentas."""

    def test_connection(self) -> str:
        """Teste explicito; envia somente uma saudacao, nunca dados do workspace."""
        try:
            response = self.chat([{"role": "user", "content": "Responda apenas OK."}], [])
        except ValueError:
            raise ProviderError("Teste de conexao recebeu uma resposta malformada do provedor.") from None
        if not isinstance(response.content, str) or not response.content.strip() or response.calls:
            raise ProviderError("Teste de conexao nao recebeu uma resposta textual valida.")
        return "Conexao e geracao de texto verificadas."


class HTTPProvider(LLMProvider):
    def __init__(self, model, *, timeout=120, client=None):
        self.model = model
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10)),
            trust_env=False, follow_redirects=False,
        )

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        origin = validate_local_url(f"{parsed.scheme}://{parsed.netloc}")
        allowed = {("GET", "/api/tags"), ("GET", "/api/version"), ("GET", "/api/ps"),
                   ("POST", "/api/show"), ("POST", "/api/chat"), ("POST", "/api/generate"),
                   ("POST", "/api/create")}
        if parsed.query or parsed.fragment or (method.upper(), parsed.path) not in allowed:
            raise ProviderError("Endpoint bloqueado pelo modo local; downloads e APIs externas nao sao permitidos.")
        if parsed.path == "/api/create":
            body = kwargs.get("json")
            if (not isinstance(body, dict) or set(body) - {"model", "from", "system", "parameters", "stream"}
                    or body.get("stream", False) is not False or set(kwargs) != {"json"}):
                raise ProviderError("Criacao permitida somente a partir de um modelo local, sem arquivos ou hosts remotos.")
            validate_local_model(body.get("model"))
            validate_local_model(body.get("from"))
        url = origin + parsed.path
        try:
            # Redirects could leave the loopback boundary, including in injected clients.
            response = self.client.request(method, url, follow_redirects=False, **kwargs)
            if not 200 <= response.status_code < 300:
                raise ProviderError(self._http_error(response))
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except httpx.TimeoutException:
            hint = "aumente timeout na configuracao ou use um modelo menor."
            raise ProviderError(f"{type(self).__name__}: timeout; {hint}") from None
        except httpx.RequestError:
            hint = "reinicie a IA local pelo aplicativo e confira se o runtime Ollama esta instalado."
            raise ProviderError(f"{type(self).__name__}: servico inacessivel; {hint}") from None
        except ValueError:
            raise ProviderError("Provedor retornou uma resposta HTTP que nao e um objeto JSON valido.") from None

    def _http_error(self, response):
        # Apenas codigos conhecidos mudam a orientacao. Mensagens, URLs e headers
        # remotos nunca vao para logs/GUI: podem conter tokens ou dados do pedido.
        code = None
        try:
            error = response.json().get("error", {})
            if isinstance(error, dict):
                code = error.get("code") or error.get("type")
        except (ValueError, AttributeError):
            pass
        status = response.status_code
        if 300 <= status < 400:
            detail = "redirecionamento bloqueado; confira o endpoint do provedor."
        elif status == 401:
            detail = "o servico local nao deve exigir credenciais; reinicie a IA pelo aplicativo."
        elif status == 403:
            detail = "acesso negado pelo servico local; modelos remotos nao sao permitidos."
        elif status == 404 or code == "model_not_found":
            detail = "modelo ausente ou endpoint indisponivel; selecione um modelo ja instalado localmente."
        elif status == 429:
            detail = "limite de requisicoes atingido; aguarde e tente novamente."
        elif code == "context_length_exceeded":
            detail = "contexto excedido; reduza o pedido ou o contexto configurado."
        elif status in (400, 422):
            detail = "pedido rejeitado; confira o modelo, o contexto e o suporte a ferramentas."
        elif status >= 500:
            detail = "servico temporariamente indisponivel; tente novamente mais tarde."
        else:
            detail = "pedido nao concluido; confira as configuracoes e a disponibilidade do provedor."
        return f"{type(self).__name__}: HTTP {status}; {detail}"

    def close(self):
        self.client.close()
