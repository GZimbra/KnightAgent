"""Perfis explicitos de recursos para o Ollama local."""

PROFILES = {
    "baixo": {"num_ctx": 4096, "num_predict": 1024, "keep_alive": "-1"},
    "medio": {"num_ctx": 8192, "num_predict": 2048, "keep_alive": "-1"},
    "alto": {"num_ctx": 16384, "num_predict": 4096, "keep_alive": "-1"},
}


def apply_profile(config, level):
    if level not in PROFILES:
        raise ValueError("Nivel de desempenho invalido.")
    config["performance"] = {"level": level}
    config["ollama"].update(PROFILES[level])
    return config
