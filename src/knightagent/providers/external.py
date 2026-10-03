"""Retired API adapters. Reject old integrations before they create a network client."""

from .base import ProviderError


class ExternalProvider:
    external = True
    supports_tools = False

    def __init__(self, *args, **kwargs):
        raise ProviderError(
            "APIs externas estao desabilitadas no modo local. "
            "O Copilot complementar e somente o aplicativo do Windows."
        )


OpenAIProvider = ExternalProvider
AnthropicProvider = ExternalProvider
GeminiProvider = ExternalProvider
CopilotProvider = ExternalProvider
