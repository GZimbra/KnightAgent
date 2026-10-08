"""Trusted assertion driver. Untrusted candidate runs only inside the OS sandbox."""

import contextlib
import io
import json
import sys


def evaluate(payload):
    scope = {"__name__": "__benchmark_candidate__"}
    # The enclosing chroot, network namespace, dropped UID and rlimits are the
    # security boundary. Restricting Python imports is not a security boundary.
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(payload["source"], "candidate.py", "exec"), scope, scope)
        function = scope.get(payload["function"])
        if not callable(function):
            raise ValueError("Required function missing")
        results = []
        for case in payload["cases"]:
            args = json.loads(json.dumps(case["args"]))
            before = json.loads(json.dumps(args))
            try:
                value = function(*args)
            except Exception as error:
                if type(error).__name__ != case.get("raises"):
                    raise
                value = {"raised": type(error).__name__}
            else:
                if case.get("raises"):
                    raise AssertionError(f"Expected {case['raises']} exception")
            results.append(value)
            if payload.get("preserve_args") and args != before:
                raise ValueError("Function mutated input arguments")
    return results


if __name__ == "__main__":
    try:
        result = evaluate(json.load(sys.stdin))
        print(json.dumps({"results": result}, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"error": f"{type(error).__name__}: {error}"}))
        raise SystemExit(1)
