import argparse
import json
import sqlite3
from pathlib import Path

from knightagent.agent.loop import Agent
from knightagent.agent.memory import MemoryStore
from knightagent.config.settings import load, build_providers, build_provider
from knightagent.knowledge import KnowledgeBase
from knightagent.automation_model import create_automation_model, DEFAULT_MODEL
from knightagent.providers.base import ProviderError
from knightagent.runtime import OllamaRuntime
from knightagent.copilot_client import CopilotClient
from knightagent.tools.files import FileTools, Workspace, WriteApproval


def main():
    parser = argparse.ArgumentParser(description="KnightAgent: agente de codigo local")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--workspace", help="Substitui a pasta configurada")
    parser.add_argument("--model", help="Substitui o modelo Ollama")
    sub = parser.add_subparsers(dest="command")
    connection = sub.add_parser("test-connection", help="Inicia e testa o Ollama local")
    connection.add_argument("provider", nargs="?", choices=["ollama"], default="ollama")
    library = sub.add_parser("knowledge", help="Biblioteca local de documentacao para automacoes")
    actions = library.add_subparsers(dest="knowledge_action", required=True)
    actions.add_parser("status", help="Contagens reais e estado da biblioteca")
    query = actions.add_parser("search", help="Pesquisa offline na documentacao")
    query.add_argument("query")
    importer = actions.add_parser("import", help="Importa documentos locais TXT, Markdown ou JSON (UTF-8)")
    importer.add_argument("paths", nargs="+", help="Arquivos ou pastas no disco local")
    importer.add_argument("--family", default="local", help="Familia da documentacao (padrao: local)")
    model = actions.add_parser("prepare-model", help="Cria perfil Ollama especializado, sem treinar pesos")
    model.add_argument("--name", default=DEFAULT_MODEL)
    model.add_argument("--base", help="Modelo base ja instalado no Ollama")
    args = parser.parse_args()
    providers = {}
    knowledge = None
    runtime = None
    complementary = None
    try:
        config = load(args.config)
        if args.model:
            config["ollama"]["model"] = args.model
        if args.command != "knowledge" or args.knowledge_action == "prepare-model":
            runtime = OllamaRuntime(config, args.config)
            runtime.start()
        if args.command == "test-connection":
            provider = build_provider(config, args.provider)
            providers[args.provider] = provider
            print(provider.test_connection())
            return 0
        if args.command == "knowledge":
            if args.knowledge_action == "prepare-model":
                print(json.dumps(create_automation_model(config, name=args.name, base=args.base), ensure_ascii=False, indent=2))
                return 0
            knowledge = KnowledgeBase(Path(args.config).resolve().parent / "knightagent-knowledge.sqlite3")
            if args.knowledge_action == "status":
                result = knowledge.stats()
            elif args.knowledge_action == "search":
                print(knowledge.search(args.query, max_chars=config["knowledge"]["max_chars"]) or "Nenhuma referencia encontrada.")
                return 0
            else:
                result = knowledge.import_local(args.paths, family=args.family)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if args.knowledge_action == "import" and result.get("documents_failed", 0):
                return 1
            return 0
        workspace = Workspace(args.workspace or config["workspace"])
        providers, roles = build_providers(config)
        tools = FileTools(workspace, WriteApproval(), config["tool_output_chars"])
        memory = (MemoryStore(Path(args.config).resolve().parent / "knightagent-memory.sqlite3", config["memory"]["scope"])
                  if config["memory"]["enabled"] else None)
        knowledge = KnowledgeBase(Path(args.config).resolve().parent / "knightagent-knowledge.sqlite3")
        complementary = CopilotClient(args.config, config["complementary"])
        agent = Agent(providers, roles, tools, config, memory=memory, knowledge=knowledge,
                      complementary=complementary)
        print(f"KnightAgent | workspace: {workspace.root}\nDigite seu pedido ou /sair.")
        print("Papeis: " + ", ".join(f"{r}={p}" for r, p in roles.items()))
        while True:
            request = input("\n> ").strip()
            if request == "/sair":
                return 0
            if request:
                try:
                    agent.run(request)
                except ProviderError as error:
                    print(f"ERRO: {error}\nNenhum fallback externo foi realizado; escritas ja aprovadas permanecem salvas.")
    except (EOFError, KeyboardInterrupt):
        print("\nSessao encerrada.")
        return 0
    except ProviderError as error:
        print(f"ERRO: {error}")
        return 1
    except (OSError, ValueError, sqlite3.Error) as error:
        # Nao imprime TOML bruto, credenciais ou corpos HTTP.
        print(f"Configuracao/workspace invalido ({type(error).__name__}). Confira README e config.example.toml.")
        return 1
    finally:
        if complementary is not None:
            complementary.close()
        if knowledge is not None:
            knowledge.close()
        for provider in providers.values():
            provider.close()
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
