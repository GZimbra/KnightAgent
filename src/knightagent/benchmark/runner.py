"""Run versioned benchmark tasks against local Ollama models."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import statistics
import tempfile
import time
import warnings

import yaml

from knightagent.agent.loop import Agent, SYSTEM
from knightagent.benchmark.validators import check_output, extract_code
from knightagent.config.settings import load
from knightagent.knowledge import SPECIALIZATION_PROMPT
from knightagent.providers.base import ProviderError
from knightagent.providers.ollama import OllamaProvider
from knightagent.runtime import OllamaRuntime
from knightagent.tools.files import FileTools, Workspace, WriteApproval


@contextmanager
def _temporary_workspace(prefix):
    path = Path(tempfile.mkdtemp(prefix=prefix))
    if path.parent.resolve() != Path(tempfile.gettempdir()).resolve():
        raise ValueError("Temporary workspace outside system temp directory")
    try:
        yield str(path)
    finally:
        # WSL can release a Windows cwd handle shortly after wsl.exe exits.
        for attempt in range(20):
            try:
                shutil.rmtree(path)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt == 19:
                    warnings.warn(f"Temporary benchmark workspace still locked: {path}")
                else:
                    time.sleep(0.25)


def load_suite(path):
    path = Path(path)
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("models"), list):
        raise ValueError("Benchmark config requires models")
    repetitions = config.get("repetitions", 3)
    if type(repetitions) is not int or not 1 <= repetitions <= 20:
        raise ValueError("repetitions must be 1..20")
    seed = config.get("seed", 20261003)
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    timeout = config.get("validator_timeout_seconds", 5)
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ValueError("validator_timeout_seconds must be 1..60")
    sandbox = config.get("sandbox")
    if (not isinstance(sandbox, dict) or set(sandbox) != {"backend", "distro", "memory_mb", "cpu_seconds", "wall_seconds"}
            or sandbox["backend"] != "wsl" or not isinstance(sandbox["distro"], str)
            or any(type(sandbox[key]) is not int for key in ("memory_mb", "cpu_seconds", "wall_seconds"))):
        raise ValueError("A configured WSL sandbox is required")
    tasks = []
    hashes = {}
    ids = set()
    for relative in config.get("task_files", []):
        file = (path.parent / relative).resolve()
        if not file.is_relative_to(path.parent.resolve()):
            raise ValueError("Task file outside suite directory")
        raw = file.read_bytes()
        hashes[relative] = sha256(raw).hexdigest()
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Task file must contain a list")
        for task in data:
            if (not isinstance(task, dict) or set(task) - {"id", "split", "language", "operation", "prompt", "fixture", "checks", "agent"}
                    or any(key not in task for key in ("id", "split", "language", "operation", "prompt", "checks"))
                    or task["split"] not in {"development", "holdout"}
                    or task["operation"] not in {"generate", "edit", "fix_bug", "format"}
                    or not isinstance(task["checks"], list) or not task["checks"]
                    or task["id"] in ids):
                raise ValueError("Invalid or duplicate benchmark task")
            ids.add(task["id"])
            tasks.append(task)
    if not tasks or not all(split in {task["split"] for task in tasks} for split in ("development", "holdout")):
        raise ValueError("Suite requires development and holdout tasks")
    config["repetitions"] = repetitions
    config["seed"] = seed
    config["validator_timeout_seconds"] = timeout
    return config, tasks, hashes


def summarize(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault((row["model"], row["mode"], row["split"], row["task_id"]), []).append(row)
    summaries = []
    for (model, mode, split, task_id), runs in grouped.items():
        evaluated = [run for run in runs if run["status"] != "skipped"]
        values = [1 if run["status"] == "passed" else 0 for run in evaluated]
        seconds = [run["wall_seconds"] for run in runs]
        metric_totals = {}
        metric_stats = {}
        for key in ("prompt_eval_count", "eval_count", "total_duration", "eval_duration", "load_duration"):
            available = [run["ollama_metrics"][key] for run in runs if key in run["ollama_metrics"]]
            metric_totals[key] = sum(available) if available else None
            metric_stats[key] = ({"mean": statistics.mean(available),
                                  "variance_population": statistics.pvariance(available)}
                                 if available else None)
        summaries.append({
            "model": model, "mode": mode, "split": split, "task_id": task_id,
            "repetitions": len(runs), "evaluated": len(evaluated),
            "passed": sum(values), "skipped": len(runs) - len(evaluated),
            "coverage": len(evaluated) / len(runs),
            "pass_rate": sum(values) / len(values) if values else None,
            "pass_variance_population": statistics.pvariance(values) if values else None,
            "mean_wall_seconds": statistics.mean(seconds),
            "wall_variance_population": statistics.pvariance(seconds),
            "ollama_metric_totals": metric_totals,
            "ollama_metric_stats": metric_stats,
        })
    return summaries


def aggregate(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row["model"], row["mode"], row["split"]), []).append(row)
    result = []
    for (model, mode, split), runs in groups.items():
        evaluated = [row for row in runs if row["status"] != "skipped"]
        times = [row["wall_seconds"] for row in runs]
        result.append({
            "model": model, "mode": mode, "split": split, "runs": len(runs),
            "passed": sum(row["status"] == "passed" for row in evaluated),
            "evaluated": len(evaluated), "skipped": len(runs) - len(evaluated),
            "coverage": len(evaluated) / len(runs),
            "pass_rate": (sum(row["status"] == "passed" for row in evaluated) / len(evaluated)
                          if evaluated else None),
            "mean_wall_seconds": statistics.mean(times),
            "wall_variance_population": statistics.pvariance(times),
            "mean_prompt_tokens": statistics.mean(row["ollama_metrics"].get("prompt_eval_count", 0) for row in runs),
            "mean_output_tokens": statistics.mean(row["ollama_metrics"].get("eval_count", 0) for row in runs),
        })
    return result


def _prompt(task):
    prompt = task["prompt"]
    fixture = task.get("fixture")
    if fixture:
        prompt += f"\n\nExisting file {fixture['path']}:\n```\n{fixture['content']}\n```"
    return prompt


def _one(provider, task, repeat, suite, config):
    start = time.monotonic()
    metrics = {}
    output = ""
    checks = []
    error = None
    with _temporary_workspace("knight-benchmark-") as directory:
        fixture = task.get("fixture")
        if fixture:
            target = Path(directory, fixture["path"])
            if not target.resolve().is_relative_to(Path(directory).resolve()):
                raise ValueError("Fixture path outside temporary directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(fixture["content"], encoding="utf-8")
        try:
            response = provider.chat(
                [{"role": "user", "content": _prompt(task)}], [],
                generation_options={"seed": suite["seed"] + repeat,
                                    "inherit_model_settings": True},
            )
            metrics = response.metrics
            output = response.content
            if not output.strip():
                raise ValueError("Empty model output")
            if fixture:
                target.write_text(extract_code(output), encoding="utf-8")
            checks = check_output(output, task["checks"], directory, suite["validator_timeout_seconds"],
                                  sandbox=suite["sandbox"])
            mandatory_skip = any(item["status"] == "skipped" and task["checks"][index].get(
                "mandatory", task["checks"][index]["type"] not in {"runtime", "vbnet_compile", "typescript_compile"})
                                 for index, item in enumerate(checks))
            status = ("failed" if any(item["status"] == "failed" for item in checks)
                      else "skipped" if mandatory_skip
                      else "passed" if any(item["status"] == "passed" for item in checks) else "skipped")
        except (ProviderError, ValueError, OSError) as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"
    return {
        "task_id": task["id"], "split": task["split"], "language": task["language"],
        "operation": task["operation"], "model": provider.model, "mode": "raw",
        "repeat": repeat + 1, "seed": suite["seed"] + repeat,
        "status": status, "error": error, "checks": checks,
        "wall_seconds": round(time.monotonic() - start, 3),
        "ollama_metrics": metrics,
        "output_sha256": sha256(output.encode("utf-8")).hexdigest() if output else None,
    }


class _MeteredAgentProvider:
    """Benchmark-only wrapper; the Agent still receives its normal response."""

    supports_tools = True
    external = False

    def __init__(self, provider, seed):
        self.provider = provider
        self.seed = seed
        self.calls = []

    def chat(self, messages, tools):
        response = self.provider.chat(messages, tools,
                                      generation_options={"seed": self.seed + len(self.calls)})
        self.calls.append(response.metrics)
        return response

    def totals(self):
        keys = ("prompt_eval_count", "eval_count", "total_duration", "eval_duration", "load_duration")
        return {key: sum(call.get(key, 0) for call in self.calls) for key in keys}


def _one_agent(provider, task, repeat, suite, config):
    start = time.monotonic()
    metered = _MeteredAgentProvider(provider, suite["seed"] + repeat * 1000)
    agent_spec = task["agent"]
    checks, error, output = [], None, ""
    with _temporary_workspace("knight-agent-benchmark-") as directory:
        fixture = task.get("fixture")
        if fixture:
            target = Path(directory, fixture["path"])
            if not target.resolve().is_relative_to(Path(directory).resolve()):
                raise ValueError("Fixture path outside temporary directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(fixture["content"], encoding="utf-8")
        tools = FileTools(Workspace(directory), WriteApproval(lambda _: "s", lambda _: None),
                          config["tool_output_chars"])
        agent = Agent({"ollama": metered}, dict.fromkeys(("planner", "executor", "reviewer"), "ollama"),
                      tools, config, emit=lambda _: None, memory=None, knowledge=None, complementary=None)
        try:
            result = agent.run(agent_spec["prompt"])
            if result is None:
                raise ValueError("Agent did not complete")
            if "target_path" in agent_spec:
                path = tools.workspace.path(agent_spec["target_path"])
                if not path.is_file() or agent_spec["target_path"] not in tools.changed:
                    raise ValueError("Agent did not save the required file")
                output = path.read_text(encoding=tools.encoding(path))
            else:
                output = result
            checks = check_output(output, task["checks"], directory, suite["validator_timeout_seconds"],
                                  sandbox=suite["sandbox"])
            mandatory_skip = any(item["status"] == "skipped" and task["checks"][index].get(
                "mandatory", task["checks"][index]["type"] not in {"runtime", "vbnet_compile", "typescript_compile"})
                                 for index, item in enumerate(checks))
            status = ("failed" if any(item["status"] == "failed" for item in checks)
                      else "skipped" if mandatory_skip
                      else "passed" if any(item["status"] == "passed" for item in checks) else "skipped")
        except (ProviderError, ValueError, OSError) as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"
    return {
        "task_id": task["id"], "split": task["split"], "language": task["language"],
        "operation": task["operation"], "model": provider.model, "mode": "agent",
        "repeat": repeat + 1, "seed": metered.seed, "status": status,
        "error": error, "checks": checks,
        "wall_seconds": round(time.monotonic() - start, 3),
        "ollama_metrics": metered.totals(), "ollama_calls": len(metered.calls),
        "output_sha256": sha256(output.encode("utf-8")).hexdigest() if output else None,
    }


def run(suite_path, app_config_path, *, splits=None):
    suite, tasks, task_hashes = load_suite(suite_path)
    if splits:
        tasks = [task for task in tasks if task["split"] in splits]
    app_config = load(app_config_path)
    original = {key: app_config["ollama"][key] for key in ("num_ctx", "num_predict", "keep_alive")}
    rows, model_errors, model_settings = [], {}, {}
    for model in suite["models"]:
        app_config["ollama"]["model"] = model
        runtime = OllamaRuntime(app_config, app_config_path)
        provider = None
        try:
            runtime.start()
            provider = OllamaProvider(**app_config["ollama"], timeout=app_config["timeout"])
            provider.preload()
            info = provider.post(provider.url + "/api/show", json={"model": model})
            model_settings[model] = {
                "system_sha256": sha256(str(info.get("system", "")).encode("utf-8")).hexdigest(),
                "parameters": info.get("parameters", ""),
                "modelfile_sha256": sha256(str(info.get("modelfile", "")).encode("utf-8")).hexdigest(),
            }
            for task in tasks:
                for repeat in range(suite["repetitions"]):
                    row = _one(provider, task, repeat, suite, app_config)
                    rows.append(row)
                    print(f"{model} raw {task['id']} #{repeat + 1}: {row['status']} ({row['wall_seconds']}s)", flush=True)
                    if task.get("agent"):
                        agent_row = _one_agent(provider, task, repeat, suite, app_config)
                        rows.append(agent_row)
                        print(f"{model} agent {task['id']} #{repeat + 1}: {agent_row['status']} ({agent_row['wall_seconds']}s)", flush=True)
        except (ProviderError, RuntimeError, OSError) as error:
            model_errors[model] = f"{type(error).__name__}: {error}"
            print(f"{model}: {model_errors[model]}", flush=True)
        finally:
            if provider:
                provider.close()
            runtime.close()
    report = {
        "schema_version": 2,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "suite_sha256": sha256(Path(suite_path).read_bytes()).hexdigest(),
        "task_sha256": task_hashes,
        "model_config": {**original, "seed_base": suite["seed"],
                         "timeout": app_config["timeout"], "context_chars": app_config["context_chars"]},
        "model_settings": model_settings,
        "effective_mode_settings": {"raw": "Modelfile system and parameters; only seed supplied",
                                    "agent": "Current Agent system prompt and configured Ollama options; seed supplied"},
        "repetitions": suite["repetitions"], "model_errors": model_errors,
        "runs": rows, "summary": summarize(rows), "aggregate": aggregate(rows),
    }
    return report


def render_summary(report):
    lines = ["# KnightAgent benchmark", "", f"Repetitions: {report['repetitions']}", "",
             "| Model | Mode | Split | Passed/evaluated | Coverage | Skipped | Mean seconds | Variance seconds² | Mean prompt tokens | Mean output tokens |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["aggregate"]:
        lines.append(f"| {row['model']} | {row['mode']} | {row['split']} | {row['passed']}/{row['evaluated']} | {row['coverage']:.0%} | {row['skipped']} | "
                     f"{row['mean_wall_seconds']:.2f} | {row['wall_variance_population']:.2f} | "
                     f"{row['mean_prompt_tokens']:.0f} | {row['mean_output_tokens']:.0f} |")
    lines.extend(["",
             "| Model | Mode | Split | Task | Pass | Mean seconds | Variance seconds² |",
             "| --- | --- | --- | --- | ---: | ---: | ---: |"])
    for row in report["summary"]:
        rate = "skipped" if row["pass_rate"] is None else f"{row['passed']}/{row['evaluated']} ({row['pass_rate']:.1%})"
        lines.append(f"| {row['model']} | {row['mode']} | {row['split']} | {row['task_id']} | {rate} | {row['mean_wall_seconds']:.2f} | {row['wall_variance_population']:.2f} |")
    for model, error in report["model_errors"].items():
        lines.append(f"\n{model}: {error}")
    skips = sorted({item["detail"] for run in report["runs"] for item in run["checks"]
                    if item["status"] == "skipped"})
    if skips:
        lines.extend(["", "Skipped checks:"] + [f"- {reason}" for reason in skips])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Offline benchmark for local Ollama models")
    parser.add_argument("--suite", default="benchmarks/suite.yaml")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output", required=True, help="JSON report path; refuses to overwrite")
    parser.add_argument("--split", choices=["development", "holdout"], action="append")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists() or output.with_suffix(".md").exists():
        parser.error("Output already exists; baseline reports are immutable")
    report = run(args.suite, args.config, splits=set(args.split or ()))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(render_summary(report), encoding="utf-8")
    print(f"Wrote {output} and {output.with_suffix('.md')}")
    return 1 if report["model_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
