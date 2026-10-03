"""Reproducible Ollama specialization; does not claim to train model weights."""

from knightagent.knowledge import SPECIALIZATION_PROMPT
from knightagent.offline import is_local_model, validate_local_model
from knightagent.providers.base import ProviderError
from knightagent.providers.ollama import OllamaProvider


DEFAULT_MODEL = "knightagent-automation:latest"


def create_automation_model(config, *, name=DEFAULT_MODEL, base=None):
    base = base or config["ollama"]["model"]
    for value in (name, base):
        validate_local_model(value)
    if name.removesuffix(":latest") == base.removesuffix(":latest"):
        raise ValueError("O perfil especializado precisa ter nome diferente do modelo base; informe --base.")
    provider = OllamaProvider(base, url=config["ollama"].get("url", "http://127.0.0.1:11435"),
                              timeout=config["timeout"])
    try:
        provider.test_connection()
        result = provider.post(provider.url + "/api/create", json={
            "model": name, "from": base, "system": SPECIALIZATION_PROMPT,
            "parameters": {"temperature": 0.2, "num_ctx": config["ollama"].get("num_ctx", 8192)},
            "stream": False,
        })
        if not isinstance(result, dict) or result.get("status") != "success":
            raise ProviderError("Ollama nao confirmou a criacao do perfil de automacao.")
        info = provider.post(provider.url + "/api/show", json={"model": name})
        if not is_local_model(info) or not isinstance(info.get("system"), str) or info["system"].strip() != SPECIALIZATION_PROMPT.strip():
            raise ProviderError("Ollama criou o perfil, mas nao confirmou as instrucoes especializadas.")
        return {"model": name, "base": base, "weights_trained": False,
                "knowledge": "Biblioteca recuperada pelo KnightAgent; nao embutida nos pesos."}
    finally:
        provider.close()
