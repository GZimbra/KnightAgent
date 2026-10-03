from pathlib import Path
from uuid import UUID

import yaml

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from knightagent.providers.ollama import OllamaProvider
from knightagent.config.performance import PROFILES
from knightagent.offline import validate_local_model, validate_local_url


PROVIDERS = {"ollama": OllamaProvider}
ENV_KEYS = {}


class StrictSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("Chave YAML duplicada ou nao textual.")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def credential(name):
    raise ValueError("Credenciais de APIs externas nao sao utilizadas no modo local.")


def load(path):
    path = Path(path).resolve()
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            config = yaml.load(path.read_text(encoding="utf-8"), Loader=StrictSafeLoader)
        except yaml.YAMLError:
            raise ValueError("YAML invalido; verifique a sintaxe de configuracao.") from None
    elif path.suffix.lower() == ".toml":
        with path.open("rb") as file:
            config = tomllib.load(file)
    else:
        raise ValueError("Use um arquivo de configuracao .yaml, .yml ou .toml.")
    if not isinstance(config, dict):
        raise ValueError("Configuracao deve ser um mapa YAML/TOML.")
    if set(config) - {"workspace", "timeout", "max_steps", "context_chars", "tool_output_chars", "format_attempts", "ollama", "providers", "roles", "performance", "memory", "knowledge", "user", "complementary"}:
        raise ValueError("Campo de configuracao desconhecido; nunca armazene chaves de API no arquivo.")
    # Migration deliberately drops retired profile/provider data and API tokens.
    config.pop("user", None)
    config.pop("providers", None)
    complementary = config.setdefault("complementary", {"copilot": False})
    if (not isinstance(complementary, dict) or set(complementary) - {"copilot", "mode", "client_id", "tenant"}
            or type(complementary.setdefault("copilot", False)) is not bool):
        raise ValueError("Configuracao do complemento Copilot invalida.")
    if "mode" not in complementary:
        # The retired checkbox only authorized manual copy/paste, never export.
        complementary["copilot"] = False
    if complementary.setdefault("mode", "account") != "account":
        raise ValueError("Use o modo account para conectar uma conta Copilot.")
    client_id = complementary.setdefault("client_id", "")
    tenant = complementary.setdefault("tenant", "organizations")
    try:
        if not isinstance(client_id, str) or not isinstance(tenant, str):
            raise ValueError()
        complementary["client_id"] = str(UUID(client_id.strip())) if client_id.strip() else ""
        complementary["tenant"] = "organizations" if tenant.strip() == "organizations" else str(UUID(tenant.strip()))
    except (ValueError, AttributeError):
        raise ValueError("Informe IDs Microsoft Entra validos; tenant pode ser organizations.") from None
    workspace = config.get("workspace", ".")
    if not isinstance(workspace, str) or not workspace:
        raise ValueError("workspace deve ser um caminho textual.")
    config["workspace"] = str((path.parent / workspace).resolve())
    for key, default, minimum, maximum in [("timeout", 120, 1, 3600), ("max_steps", 30, 1, 200), ("context_chars", 24000, 8000, 200000), ("tool_output_chars", 6000, 256, 20000), ("format_attempts", 3, 1, 5)]:
        value = config.setdefault(key, default)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"Configuracao invalida: {key}.")
    local = config.get("ollama", {})
    if not isinstance(local, dict) or set(local) - {"model", "url", "num_ctx", "num_predict", "keep_alive"} or not isinstance(local.get("model"), str) or not local["model"].strip():
        raise ValueError("Configure ollama.model e somente campos permitidos.")
    local["model"] = validate_local_model(local["model"].strip())
    local["url"] = validate_local_url(local.get("url", "http://127.0.0.1:11435"))
    num_ctx = local.setdefault("num_ctx", 8192)
    if type(num_ctx) is not int or not 2048 <= num_ctx <= 131072:
        raise ValueError("ollama.num_ctx deve estar entre 2048 e 131072.")
    num_predict = local.setdefault("num_predict", 2048)
    if type(num_predict) is not int or not 128 <= num_predict <= 16384:
        raise ValueError("ollama.num_predict deve estar entre 128 e 16384.")
    keep_alive = local.setdefault("keep_alive", "-1")
    if not isinstance(keep_alive, str) or keep_alive not in {"-1", "0", "5m", "30m"}:
        raise ValueError("ollama.keep_alive deve ser -1, 0, 5m ou 30m.")
    performance = config.setdefault("performance", {"level": "medio"})
    if not isinstance(performance, dict) or set(performance) != {"level"} or performance["level"] not in PROFILES:
        raise ValueError("performance.level deve ser baixo, medio ou alto.")
    memory = config.setdefault("memory", {"enabled": True, "scope": "global"})
    if not isinstance(memory, dict) or set(memory) - {"enabled", "scope"} or type(memory.get("enabled", True)) is not bool or memory.get("scope", "global") not in {"global", "workspace"}:
        raise ValueError("memory deve conter enabled booleano e scope global ou workspace.")
    memory.setdefault("enabled", True)
    memory.setdefault("scope", "global")
    knowledge = config.setdefault("knowledge", {})
    if not isinstance(knowledge, dict) or set(knowledge) - {"enabled", "max_chars"}:
        raise ValueError("knowledge deve conter enabled e max_chars.")
    if type(knowledge.setdefault("enabled", True)) is not bool:
        raise ValueError("knowledge.enabled deve ser booleano.")
    knowledge["enabled"] = True
    if type(knowledge.setdefault("max_chars", 6000)) is not int or not 500 <= knowledge["max_chars"] <= 12000:
        raise ValueError("knowledge.max_chars deve estar entre 500 e 12000.")
    if not isinstance(config.get("roles", {}), dict) or set(config.get("roles", {})) - {"planner", "executor", "reviewer"}:
        raise ValueError("Papel desconhecido.")
    config["roles"] = dict.fromkeys(("planner", "executor", "reviewer"), "ollama")
    validate_roles(config)
    return config


def validate_roles(config):
    for role, selected in config.get("roles", {}).items():
        if role not in {"planner", "executor", "reviewer"} or selected != "ollama":
            raise ValueError("Todos os papeis devem usar somente Ollama local.")


def build_provider(config, name, key=None):
    """Only the local provider can be constructed, irrespective of saved legacy data."""
    if name != "ollama" or key is not None:
        raise ValueError("Somente Ollama local esta disponivel; APIs externas estao bloqueadas.")
    return OllamaProvider(**config["ollama"], timeout=config["timeout"])


def build_providers(config):
    validate_roles(config)
    return {"ollama": build_provider(config, "ollama")}, dict.fromkeys(("planner", "executor", "reviewer"), "ollama")
