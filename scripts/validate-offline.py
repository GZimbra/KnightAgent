"""Real local smoke test. Requires the private runtime, weights and firewall rules."""
import json
from pathlib import Path
import time

from knightagent.agent.loop import Agent
from knightagent.config.settings import load, build_providers
from knightagent.copilot import detect_copilot
from knightagent.knowledge import KnowledgeBase
from knightagent.runtime import OllamaRuntime
from knightagent.tools.files import FileTools, Workspace, WriteApproval


def main():
    root = Path(__file__).resolve().parent.parent
    config = load(root / "config.yaml")
    runtime = OllamaRuntime(config, root / "config.yaml")
    providers = {}
    library = None
    report = {"model": config["ollama"]["model"], "network": "Windows firewall + loopback + cloud disabled"}
    process = None
    try:
        began = time.monotonic()
        report["start_status"] = runtime.start()
        report["startup_seconds"] = round(time.monotonic() - began, 3)
        process = runtime._process
        began = time.monotonic()
        report["preload_status"] = runtime.preload()
        report["preload_seconds"] = round(time.monotonic() - began, 3)
        providers, roles = build_providers(config)
        library = KnowledgeBase(root / "knightagent-knowledge.sqlite3")
        tools = FileTools(Workspace(root), WriteApproval(lambda _: "n", lambda _: None), config["tool_output_chars"])
        events = []
        agent = Agent(providers, roles, tools, config, emit=events.append, knowledge=library)
        began = time.monotonic()
        report["response"] = agent.run("Segundo a biblioteca local, para que serve Option Explicit no VBA? Responda em ate duas frases, sem criar ou editar arquivos.")
        report["response_seconds"] = round(time.monotonic() - began, 3)
        report["local_references_used"] = bool(agent.reference_context)
        report["files_written"] = tools.write_count
        report["copilot_application"] = detect_copilot()
        report["resident_models"] = [m.get("name") for m in providers["ollama"].get(config["ollama"]["url"] + "/api/ps").get("models", [])]
        assert report["response"] and report["local_references_used"]
        assert tools.write_count == 0
    finally:
        for provider in providers.values():
            provider.close()
        if library is not None:
            library.close()
        runtime.close()
        report["process_stopped"] = process is not None and process.poll() is not None and not runtime.running
        (root / "build" / "offline-smoke.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    assert report["process_stopped"]
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
