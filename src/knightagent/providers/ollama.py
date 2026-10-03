import json

from knightagent.agent.parsing import ENVELOPE, FormatError, parse_envelope
from knightagent.offline import is_local_model, validate_local_model, validate_local_url
from .base import ChatResponse, HTTPProvider, ToolCall, ProviderError


class OllamaProvider(HTTPProvider):
    def __init__(self, model, *, url="http://127.0.0.1:11435", num_ctx=8192, num_predict=2048, keep_alive="-1", **kwargs):
        self.url = validate_local_url(url)
        super().__init__(validate_local_model(model), **kwargs)
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        # The API parses duration strings; "-1" is not a Go duration. Use a JSON
        # number for the session-persistent setting, not the configuration string.
        self.keep_alive = -1 if keep_alive == "-1" else keep_alive
        self.native = None

    def test_connection(self):
        inventory = self.get(self.url + "/api/tags").get("models")
        if not isinstance(inventory, list):
            raise ProviderError("Ollama retornou uma lista de modelos invalida.")
        # A cloud alias can have an ordinary name. Check inventory before /show,
        # which can otherwise contact the upstream server for a remote model.
        canonical = self.model if ":" in self.model else self.model + ":latest"
        matches = [entry for entry in inventory if isinstance(entry, dict)
                   and any(isinstance(name, str) and name in {self.model, canonical}
                           for name in (entry.get("name"), entry.get("model")))]
        if not matches:
            raise ProviderError("Modelo ausente: escolha um modelo ja instalado localmente. Nenhum download sera feito.")
        if not all(is_local_model(entry) for entry in matches):
            raise ProviderError("Modelo remoto/cloud bloqueado, mesmo que possua um alias local.")
        info = self.post(self.url + "/api/show", json={"model": self.model})
        if not is_local_model(info):
            raise ProviderError("Modelo remoto/cloud bloqueado pelo modo local.")
        if not isinstance(info, dict) or not (info.get("details") or info.get("capabilities") or info.get("modelfile")):
            raise ProviderError("Ollama retornou informacoes de modelo invalidas.")
        capabilities = info.get("capabilities", [])
        if not isinstance(capabilities, list):
            raise ProviderError("Ollama retornou capacidades de modelo invalidas.")
        self.native = "tools" in capabilities
        return f"Ollama local conectado; modelo {self.model} instalado. Nenhum download realizado."

    def preload(self):
        self.test_connection()
        data = self.post(self.url + "/api/generate", json={
            "model": self.model, "prompt": "", "stream": False, "keep_alive": self.keep_alive,
            "options": {"num_ctx": self.num_ctx},
        })
        if not is_local_model(data) or data.get("done") is not True:
            raise ProviderError("Ollama nao confirmou o carregamento local do modelo.")
        return f"IA local pronta: {self.model}."

    def chat(self, messages, tools):
        if self.native is None:
            self.test_connection()
        payload = {"model": self.model, "messages": list(messages), "stream": False,
                   "keep_alive": self.keep_alive,
                   "options": {"num_ctx": self.num_ctx, "num_predict": self.num_predict, "temperature": 0.2}}
        if tools and self.native:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
        elif tools:
            payload["format"] = ENVELOPE
            payload["messages"] = [{"role": "system", "content":
                'Responda somente JSON com content (string) e tool_calls (array de {name, arguments}). '
                'Para concluir, tool_calls deve ser []. Ferramentas: ' + json.dumps(tools)}] + list(messages)
        data = self.post(self.url + "/api/chat", json=payload)
        if not is_local_model(data):
            raise ProviderError("Resposta de modelo remoto rejeitada pelo modo local.")
        if isinstance(data, dict) and data.get("done_reason") == "length":
            raise ProviderError("Ollama atingiu o limite de saida; aumente num_predict ou divida a tarefa. Nenhuma ferramenta desta resposta foi executada.")
        try:
            msg = data["message"]
            if tools and not self.native:
                return parse_envelope(msg["content"], tools)
            return ChatResponse(msg.get("content", ""), [ToolCall(c["function"]["name"], c["function"]["arguments"]) for c in msg.get("tool_calls", [])])
        except (KeyError, TypeError, AttributeError):
            raise FormatError("Resposta Ollama malformada.") from None
