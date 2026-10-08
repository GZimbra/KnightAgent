"""Executable checks and explicit skips for unavailable language runtimes."""

import ast
import json
from pathlib import Path
import re

from .sandbox import SandboxUnavailable, execute



def extract_code(text):
    # Code tasks assess the code block even if the model adds surrounding prose;
    # strict formatting is measured separately by JSON/format tasks.
    match = re.search(r"```[^\n]*\n(.*?)```", text, re.S)
    return match.group(1) if match else text


def _code_only(text):
    if re.fullmatch(r"\s*```[^\n]*\n.*?```\s*", text, re.S):
        return True
    return "```" not in text and not re.search(r"(?im)^\s*(?:here is|explanation|this function)\b", text)


def _python_function(source, check, directory, sandbox):
    payload = {"source": source, "function": check["function"], "cases": check["cases"],
               "preserve_args": check.get("preserve_args", False)}
    try:
        data = execute(payload, distro=sandbox["distro"], memory_mb=sandbox["memory_mb"],
                       cpu_seconds=sandbox["cpu_seconds"], wall_seconds=sandbox["wall_seconds"],
                       directory=directory)
    except SandboxUnavailable as error:
        return "skipped", str(error)
    if "error" in data:
        return "failed", str(data.get("error", "Python test failed"))[:300]
    expected = [{"raised": case["raises"]} if "raises" in case else case["expected"]
                for case in check["cases"]]
    if data.get("results") != expected:
        return "failed", f"Expected {expected!r}, got {data.get('results')!r}"[:300]
    return "passed", "All function assertions passed"


def _vba_static(source, check):
    lines = [line.strip() for line in source.splitlines()]
    subs = sum(bool(re.match(r"(?i)^(?:public |private )?(?:sub|function)\s+\w+\s*\(", line)) for line in lines)
    ends = sum(line.lower() in {"end sub", "end function"} for line in lines)
    required = check.get("required", [])
    if not subs or subs != ends or not all(re.search(pattern, source, re.I | re.M) for pattern in required):
        return "failed", "VBA static structure or required patterns invalid"
    return "passed", "VBA static structure passed; Excel compile/runtime unavailable"


def _vbnet_static(source, check):
    lines = [line.strip().lower() for line in source.splitlines()]
    modules = sum(bool(re.match(r"^(?:public |friend )?module\s+\w+", line)) for line in lines)
    ends = sum(line == "end module" for line in lines)
    functions = sum(bool(re.match(r"^(?:public |private |friend )?function\s+\w+", line)) for line in lines)
    function_ends = sum(line == "end function" for line in lines)
    if modules != 1 or ends != 1 or functions != function_ends:
        return "failed", "VB.NET module/function structure invalid"
    if not all(re.search(pattern, source, re.I | re.M) for pattern in check.get("required", [])):
        return "failed", "VB.NET required structure missing"
    return "passed", "VB.NET static structure valid; compilation separately reported"


def _typescript_static(source, check):
    # Delimiter balance catches incomplete Office Scripts even without the
    # ExcelScript declarations required for a full TypeScript compilation.
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    quote = None
    escaped = False
    for char in source:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "\"'`":
            quote = char
        elif char in "([{":
            stack.append(char)
        elif char in ")]}":
            if not stack or stack.pop() != pairs[char]:
                return "failed", "TypeScript delimiters invalid"
    if quote or stack or not re.search(r"function\s+main\s*\(\s*workbook\s*:\s*ExcelScript\.Workbook", source):
        return "failed", "Office Scripts static structure invalid"
    if not all(re.search(pattern, source, re.I | re.M) for pattern in check.get("required", [])):
        return "failed", "Office Scripts required structure missing"
    return "passed", "Office Scripts static structure valid; compilation separately reported"


def _vbnet_compile(source, directory, timeout):
    # Never compile untrusted output on the Windows host. The WSL sandbox only
    # mounts a Python runtime; a .NET SDK is not available inside that chroot.
    return "skipped", ".NET SDK unavailable inside the isolated benchmark"


def _typescript_compile(source, directory, timeout):
    # Office Scripts requires ExcelScript declarations and an isolated compiler.
    return "skipped", "ExcelScript type declarations unavailable in isolated benchmark"


def check_output(text, checks, directory, timeout, sandbox=None):
    source = extract_code(text)
    results = []
    for check in checks:
        kind = check["type"]
        try:
            if kind == "python_syntax":
                ast.parse(source)
                status, detail = "passed", "Python syntax valid"
            elif kind == "python_function":
                if sandbox is None:
                    raise ValueError("Sandbox configuration required for Python execution")
                status, detail = _python_function(source, check, directory, sandbox)
            elif kind == "vba_static":
                status, detail = _vba_static(source, check)
            elif kind == "vbnet_static":
                status, detail = _vbnet_static(source, check)
            elif kind == "typescript_static":
                status, detail = _typescript_static(source, check)
            elif kind == "vbnet_compile":
                status, detail = _vbnet_compile(source, directory, timeout)
            elif kind == "typescript_compile":
                status, detail = _typescript_compile(source, directory, timeout)
            elif kind == "json_schema":
                obj = json.loads(text)
                types = {"string": str, "integer": int, "array": list, "object": dict, "boolean": bool}
                valid = isinstance(obj, dict) and set(obj) == set(check["fields"])
                valid = valid and all(type(obj[key]) is types[value] for key, value in check["fields"].items())
                status, detail = ("passed", "JSON format valid") if valid else ("failed", "JSON schema mismatch")
            elif kind == "json_equals":
                status, detail = (("passed", "JSON value matched") if json.loads(text) == check["expected"]
                                  else ("failed", "JSON value mismatch"))
            elif kind == "code_only":
                status, detail = (("passed", "Only code was returned") if _code_only(text)
                                  else ("failed", "Explanatory text outside code"))
            elif kind == "text_contains":
                valid = all(re.search(pattern, source, re.I | re.M) for pattern in check["patterns"])
                status, detail = ("passed", "Required patterns found") if valid else ("failed", "Required pattern missing")
            elif kind == "text_not_contains":
                valid = not any(re.search(pattern, source, re.I | re.M) for pattern in check["patterns"])
                status, detail = ("passed", "Forbidden patterns absent") if valid else ("failed", "Forbidden pattern found")
            elif kind == "runtime":
                status, detail = "skipped", f"{check['name']} runtime/compiler not available in the isolated benchmark"
            else:
                raise ValueError(f"Unknown validator: {kind}")
        except (SyntaxError, ValueError, TypeError, re.error) as error:
            status, detail = "failed", f"{type(error).__name__}: {error}"[:300]
        results.append({"type": kind, "status": status, "detail": detail})
    return results
