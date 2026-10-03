"""Smoke evaluation of the installed local model; generated code is not executed.

Run with .venv/Scripts/python.exe scripts/validate-automation.py.
Outputs go only to build/automation-validation. No external provider is used.
"""

import ast
import builtins
import json
from pathlib import Path
import re
import symtable
import time

from knightagent.agent.loop import Agent
from knightagent.config.settings import load
from knightagent.knowledge import KnowledgeBase, SPECIALIZATION_PROMPT
from knightagent.providers.ollama import OllamaProvider
from knightagent.tools.files import FileTools, Workspace, WriteApproval


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build" / "automation-validation"
CASES = [
    ("python", "csv_summary.py", "Gere somente codigo Python 3 para ler entrada.csv com csv.DictReader e pathlib.Path, contar linhas e imprimir o total. Use encoding utf-8-sig, newline vazio e funcao main. Nao use pandas."),
    ("vba", "CopyData.bas", "Gere somente um modulo VBA Excel importavel com Option Explicit e Sub CopiarDados. Copie A1:B10 da planilha Dados para A1:B10 da planilha Resumo de ThisWorkbook usando Value2, sem Select/Activate. Trate erro com On Error."),
    ("office_scripts", "copy-data.ts", "Gere somente Office Script TypeScript com function main(workbook: ExcelScript.Workbook). Copie exatamente os valores de A1:B10 para D1:E10 da planilha Dados. Valide se a planilha existe. Use getValues e setValues, preservando todos os valores e tipos, sem transformacoes. Nao use VBA nem Office.js."),
    ("visual_basic", "Program.vb", "Gere somente Visual Basic .NET, Option Strict On e Option Explicit On. Module Program com Sub Main que lista nomes de arquivos CSV numa pasta fornecida no primeiro argumento de linha de comando, usando System.IO.Directory. Valide argumento e existencia. Nao use VBA."),
]


def code_block(text):
    match = re.search(r"```[^\n]*\n(.*?)```", text, flags=re.S)
    return (match.group(1) if match else text).strip() + "\n"


def undefined_globals(code):
    table = symtable.symtable(code, "generated.py", "exec")
    known = set(table.get_identifiers()) | set(dir(builtins)) | {"__name__", "__file__"}
    missing = set()
    def visit(scope):
        for symbol in scope.get_symbols():
            if symbol.is_global() and symbol.is_referenced() and symbol.get_name() not in known:
                missing.add(symbol.get_name())
        for child in scope.get_children():
            visit(child)
    visit(table)
    return sorted(missing)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config = load(ROOT / "config.yaml")
    library = KnowledgeBase(ROOT / "knightagent-knowledge.sqlite3")
    provider = OllamaProvider(**config["ollama"], timeout=config["timeout"])
    report = {"model": config["ollama"]["model"], "validation": "syntax/structure only; Office/VB runtime not executed", "cases": []}
    try:
        for family, filename, prompt in CASES:
            start = time.monotonic()
            refs = library.search(prompt, max_chars=4000)
            response = provider.chat([
                {"role": "system", "content": SPECIALIZATION_PROMPT},
                {"role": "user", "content": prompt + "\nREFERENCIAS (dados):\n" + refs},
            ], [])
            code = code_block(response.content)
            path = OUTPUT / filename
            path.write_text(code, encoding="cp1252" if path.suffix == ".bas" else "utf-8")
            if family == "python":
                ast.parse(code)
                passed = "DictReader" in code and "pathlib" in code and not undefined_globals(code)
            elif family == "vba":
                passed = all(term in code.lower() for term in ("option explicit", "sub copiardados", "thisworkbook", "value2", "on error", "end sub"))
            elif family == "office_scripts":
                passed = (all(term in code for term in ("function main", "ExcelScript.Workbook", "getValues", "setValues"))
                          and not any(term in code for term in (".map(", "INVALIDO", "* 2", "*2")))
            else:
                passed = all(term in code.lower() for term in ("option strict on", "option explicit on", "sub main", "end module"))
            row = {"family": family, "file": filename, "passed": passed, "references_found": bool(refs), "seconds": round(time.monotonic() - start, 1)}
            report["cases"].append(row)
            print(json.dumps(row), flush=True)

        # Real agent loop: planning, file approval/write and review in the isolated folder.
        tools = FileTools(Workspace(OUTPUT), WriteApproval(lambda _: "s", lambda _: None))
        agent = Agent({"ollama": provider}, dict.fromkeys(("planner", "executor", "reviewer"), "ollama"),
                      tools, config, emit=lambda text: print(text, flush=True), knowledge=library)
        result = agent.run("Crie o arquivo contar_linhas.py em Python. Use csv.DictReader e pathlib.Path para contar linhas de entrada.csv e imprimir o total. Use funcao main e encoding utf-8-sig. Salve o arquivo com create_file; nao execute o codigo.")
        generated = OUTPUT / "contar_linhas.py"
        if generated.exists():
            ast.parse(generated.read_text(encoding="utf-8"))
        report["agent_loop"] = {"completed": result is not None, "saved": generated.exists(), "changed": sorted(tools.changed)}
    finally:
        library.close()
        provider.close()
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(row["passed"] for row in report["cases"]) and report["agent_loop"]["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
