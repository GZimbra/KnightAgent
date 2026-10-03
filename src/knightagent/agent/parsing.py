import json

from knightagent.providers.base import ChatResponse, ToolCall


class FormatError(ValueError):
    pass


ENVELOPE = {
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "tool_calls": {"type": "array", "maxItems": 8, "items": {
            "type": "object", "properties": {
                "name": {"type": "string"}, "arguments": {"type": "object"}},
            "required": ["name", "arguments"], "additionalProperties": False}},
    },
    "required": ["content", "tool_calls"], "additionalProperties": False,
}


def validate_calls(response, tools):
    definitions = {t["name"]: t["parameters"] for t in tools}
    if not isinstance(response.content, str) or len(response.calls) > 8:
        raise FormatError("content deve ser texto; no maximo 8 chamadas por resposta.")
    for call in response.calls:
        if not isinstance(call.name, str) or call.name not in definitions:
            raise FormatError("Ferramenta desconhecida ou indisponivel neste papel.")
        schema = definitions[call.name]
        args = call.arguments
        if not isinstance(args, dict):
            raise FormatError("arguments deve ser objeto JSON.")
        if set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
            raise FormatError("Argumentos ausentes ou desconhecidos.")
        for name, value in args.items():
            spec = schema["properties"][name]
            expected = str if spec["type"] == "string" else int
            if type(value) is not expected:
                raise FormatError(f"Tipo invalido para {name}.")
            if expected is int and not spec.get("minimum", 1) <= value <= spec.get("maximum", 1000000):
                raise FormatError(f"{name} fora dos limites.")
    return response


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Chave JSON duplicada.")
        result[key] = value
    return result


def parse_envelope(text, tools):
    try:
        data = json.loads(text, object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != {"content", "tool_calls"}:
            raise ValueError()
        if not isinstance(data["tool_calls"], list):
            raise ValueError()
        calls = []
        for item in data["tool_calls"]:
            if not isinstance(item, dict) or set(item) != {"name", "arguments"}:
                raise ValueError()
            calls.append(ToolCall(item["name"], item["arguments"]))
        return validate_calls(ChatResponse(data["content"], calls), tools)
    except (ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, FormatError):
            raise
        raise FormatError('Responda apenas JSON: {"content":"texto", "tool_calls":[{"name":"ferramenta", "arguments":{}}]}.') from None
