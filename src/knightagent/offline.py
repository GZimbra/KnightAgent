"""Shared, fail-closed checks for the application's local Ollama boundary."""

import re
from urllib.parse import urlsplit


def validate_local_url(url):
    """Accept only a loopback HTTP origin; canonicalize localhost without DNS."""
    if not isinstance(url, str) or not url or any(char.isspace() for char in url):
        raise ValueError("Ollama deve usar HTTP em loopback local.")
    try:
        parsed = urlsplit(url)
        port = 11434 if parsed.port is None else parsed.port
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or not 1 <= port <= 65535 or parsed.netloc.endswith(":")):
            raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError("Ollama deve usar HTTP em loopback local, sem caminho ou credenciais.") from None
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{port}"


def validate_local_model(model):
    """Reject cloud names and remote registry URLs before any API request."""
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:/-]{0,254}", model):
        raise ValueError("Informe o nome de um modelo Ollama instalado localmente.")
    lowered = model.lower()
    if ("//" in model or model.count(":") > 1 or model.startswith(("http:", "https:"))
            or any(part in {".", "..", ""} for part in model.split("/"))
            or re.search(r"(?:^|[:/._-])cloud(?:$|[:/._-])", lowered)
            or ("/" in model and ("." in model.split("/")[0] or ":" in model.split("/")[0]))):
        raise ValueError("Modelos cloud ou remotos estao bloqueados; escolha um modelo instalado localmente.")
    return model


def is_local_model(info):
    """Check inventory/show metadata, including remote aliases with innocent names."""
    if not isinstance(info, dict):
        return False
    if any(info.get(key) for key in ("remote_host", "remote_model")):
        return False
    details = info.get("details", {})
    if isinstance(details, dict) and any(details.get(key) for key in ("remote_host", "remote_model")):
        return False
    for key in ("name", "model"):
        if key in info:
            try:
                validate_local_model(info[key])
            except ValueError:
                return False
    return True
