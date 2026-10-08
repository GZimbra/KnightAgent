import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from knightagent.benchmark.runner import _one, _temporary_workspace, aggregate, load_suite, run, summarize
from knightagent.benchmark.compare import compare, decision
from knightagent.benchmark.validators import check_output, extract_code
from knightagent.benchmark.sandbox import SandboxUnavailable
from knightagent.providers.ollama import OllamaProvider


ROOT = Path(__file__).resolve().parents[1]


class BenchmarkSuiteTests(unittest.TestCase):
    def test_temporary_workspace_retries_windows_file_lock(self):
        import shutil
        real_remove = shutil.rmtree
        attempts = [0]
        def flaky_remove(path):
            attempts[0] += 1
            if attempts[0] == 1:
                raise PermissionError("locked")
            return real_remove(path)
        with patch("knightagent.benchmark.runner.shutil.rmtree", side_effect=flaky_remove) as remove, patch(
            "knightagent.benchmark.runner.time.sleep"
        ):
            with _temporary_workspace("knight-benchmark-test-") as directory:
                path = Path(directory)
                path.joinpath("data.txt").write_text("ok", encoding="utf-8")
            self.assertFalse(path.exists())
            self.assertEqual(remove.call_count, 2)

    def test_suite_is_data_driven_and_split(self):
        suite, tasks, hashes = load_suite(ROOT / "benchmarks" / "suite.yaml")
        self.assertEqual(suite["repetitions"], 3)
        self.assertEqual(set(hashes), {"development.json", "holdout.json", "holdout_extra.json"})
        self.assertGreaterEqual(sum(task["split"] == "holdout" for task in tasks), 12)
        self.assertEqual({task["split"] for task in tasks}, {"development", "holdout"})
        self.assertTrue({"python", "vba", "visual_basic_dotnet", "office_scripts"} <= {task["language"] for task in tasks})
        self.assertTrue({"generate", "edit", "fix_bug", "format"} <= {task["operation"] for task in tasks})

    def test_function_runner_executes_asserts_in_os_sandbox(self):
        check = {"type": "python_function", "function": "double", "cases": [{"args": [3], "expected": 6}]}
        with tempfile.TemporaryDirectory() as directory:
            with patch("knightagent.benchmark.validators.execute", side_effect=[{"results": [6]}, {"error": "MemoryError"}]) as execute:
                good = check_output("def double(value):\n    return value * 2\n", [check], directory, 3, sandbox={"distro":"kali-linux","memory_mb":512,"cpu_seconds":3,"wall_seconds":10})
                bad = check_output("def double(value):\n    return value * 2\n", [check], directory, 3, sandbox={"distro":"kali-linux","memory_mb":512,"cpu_seconds":3,"wall_seconds":10})
                self.assertEqual(execute.call_count, 2)
        self.assertEqual(good[0]["status"], "passed")
        self.assertEqual(bad[0]["status"], "failed")

    def test_function_runner_allows_pure_comprehensions_and_string_methods(self):
        check = {"type": "python_function", "function": "clean", "cases": [
            {"args": [[" a ", " ", "b"]], "expected": "a b"}]}
        with tempfile.TemporaryDirectory() as directory:
            sandbox={"distro":"kali-linux","memory_mb":512,"cpu_seconds":3,"wall_seconds":10}
            with patch("knightagent.benchmark.validators.execute", side_effect=[{"results": ["a b"]}, {"results": ["wrong"]}]):
                result = check_output("def clean(words):\n    return ' '.join(w.strip() for w in words if w.strip())\n",
                                      [check], directory, 3, sandbox=sandbox)
                escape = check_output("def clean(words):\n    return words.__class__\n", [check], directory, 3, sandbox=sandbox)
        self.assertEqual(result[0]["status"], "passed")
        self.assertEqual(escape[0]["status"], "failed")

    def test_function_runner_detects_input_mutation(self):
        check = {"type": "python_function", "function": "ordered", "preserve_args": True,
                 "cases": [{"args": [[3, 1]], "expected": [1, 3]}]}
        with tempfile.TemporaryDirectory() as directory:
            with patch("knightagent.benchmark.validators.execute", return_value={"error":"Function mutated input arguments"}):
                result = check_output("def ordered(values):\n    values.sort()\n    return values\n",
                                      [check], directory, 3, sandbox={"distro":"kali-linux","memory_mb":512,"cpu_seconds":3,"wall_seconds":10})
        self.assertEqual(result[0]["status"], "failed")

    def test_json_format_and_static_vba(self):
        with tempfile.TemporaryDirectory() as directory:
            checks = check_output('{"status":"ready","count":3}', [
                {"type": "json_schema", "fields": {"status": "string", "count": "integer"}},
                {"type": "json_equals", "expected": {"status": "ready", "count": 3}},
            ], directory, 3)
            vba = check_output("Option Explicit\nPublic Sub Work()\nEnd Sub\n", [
                {"type": "vba_static", "required": ["Option Explicit"]}], directory, 3)
        self.assertEqual([row["status"] for row in checks], ["passed", "passed"])
        self.assertEqual(vba[0]["status"], "passed")

    def test_office_and_vbnet_static_checks_with_optional_runtime(self):
        office = "function main(workbook: ExcelScript.Workbook) { const w = workbook.getWorksheet('Data'); w.getUsedRange().getValues(); w.getRange('A1').setValues([[1]]); }"
        vbnet = "Option Strict On\nPublic Module FrequencyOps\nPublic Function CountOccurrences(values As Integer(), target As Integer) As Integer\nReturn 0\nEnd Function\nEnd Module"
        with tempfile.TemporaryDirectory() as directory:
            office_result = check_output(office, [{"type": "typescript_static", "required": ["getValues"]},
                                                  {"type": "typescript_compile", "mandatory": False}], directory, 3)
            vb_result = check_output(vbnet, [{"type": "vbnet_static", "required": ["Option Strict On"]},
                                             {"type": "vbnet_compile", "mandatory": False}], directory, 3)
            broken = check_output(office[:-1], [{"type": "typescript_static"}], directory, 3)
        self.assertEqual([check["status"] for check in office_result], ["passed", "skipped"])
        self.assertEqual([check["status"] for check in vb_result], ["passed", "skipped"])
        self.assertEqual(broken[0]["status"], "failed")

    def test_sandbox_unavailable_is_skipped(self):
        check = {"type": "python_function", "function": "f", "cases": [{"args": [], "expected": 1}]}
        with tempfile.TemporaryDirectory() as directory, patch(
            "knightagent.benchmark.validators.execute", side_effect=SandboxUnavailable("WSL missing")
        ):
            result = check_output("def f(): return 1", [check], directory, 3,
                                  sandbox={"distro":"kali-linux","memory_mb":512,"cpu_seconds":3,"wall_seconds":10})
        self.assertEqual(result[0]["status"], "skipped")

    def test_code_is_extracted_without_accepting_extra_json_text(self):
        self.assertEqual(extract_code("Here is code:\n```python\ndef f():\n    return 1\n```\nExplanation"),
                         "def f():\n    return 1\n")
        with tempfile.TemporaryDirectory() as directory:
            result = check_output("```python\ndef f():\n    return 1\n```\nExplanation",
                                  [{"type": "code_only"}], directory, 3)
        self.assertEqual(result[0]["status"], "failed")

    def test_metrics_mean_and_population_variance(self):
        rows = [dict(model="m", mode="raw", split="development", task_id="t", status=status,
                     wall_seconds=seconds, ollama_metrics={"eval_count": tokens})
                for status, seconds, tokens in (("passed", 1, 10), ("failed", 2, 20), ("passed", 3, 30))]
        result = summarize(rows)[0]
        self.assertEqual(result["pass_rate"], 2 / 3)
        self.assertAlmostEqual(result["pass_variance_population"], 2 / 9)
        self.assertEqual(result["mean_wall_seconds"], 2)
        self.assertAlmostEqual(result["wall_variance_population"], 2 / 3)
        self.assertEqual(result["ollama_metric_totals"]["eval_count"], 60)
        self.assertEqual(result["ollama_metric_stats"]["eval_count"]["mean"], 20)
        self.assertAlmostEqual(result["ollama_metric_stats"]["eval_count"]["variance_population"], 200 / 3)
        self.assertEqual(aggregate(rows)[0]["passed"], 2)
        self.assertEqual(aggregate(rows)[0]["coverage"], 1)

    def test_runner_records_seed_and_skipped_compiler(self):
        provider = Mock(model="m")
        provider.chat.return_value = Mock(content="Option Strict On\n", metrics={"eval_count": 12})
        task = {"id": "vb", "split": "holdout", "language": "visual_basic_dotnet",
                "operation": "generate", "prompt": "code", "checks": [
                    {"type": "text_contains", "patterns": ["Option Strict On"]},
                    {"type": "runtime", "name": "compiler", "mandatory": True}]}
        row = _one(provider, task, 1, {"seed": 40, "validator_timeout_seconds": 2, "sandbox": {}}, {})
        self.assertEqual(row["seed"], 41)
        self.assertEqual(row["status"], "skipped")
        self.assertEqual(row["ollama_metrics"]["eval_count"], 12)
        self.assertEqual(provider.chat.call_args.kwargs["generation_options"], {"seed": 41, "inherit_model_settings": True})

    def test_runner_reports_empty_output_and_unavailable_model(self):
        provider = Mock(model="m")
        provider.chat.return_value = Mock(content="", metrics={})
        task = {"id": "empty", "split": "development", "language": "json",
                "operation": "format", "prompt": "object", "checks": [{"type": "json_schema", "fields": {}}]}
        row = _one(provider, task, 0, {"seed": 1, "validator_timeout_seconds": 2}, {})
        self.assertEqual(row["status"], "failed")
        self.assertIn("Empty model output", row["error"])
        with patch("knightagent.benchmark.runner.OllamaRuntime") as runtime:
            runtime.return_value.start.side_effect = RuntimeError("service unavailable")
            report = run(ROOT / "benchmarks" / "suite.yaml", ROOT / "config.example.yaml")
        self.assertEqual(report["runs"], [])
        self.assertEqual(set(report["model_errors"]), {"qwen2.5:7b", "knightagent-automation:latest"})

    def test_ollama_metrics_are_propagated_without_changing_message(self):
        provider = OllamaProvider("qwen2.5:7b")
        self.addCleanup(provider.close)
        provider.native = True
        data = {"message": {"content": "OK", "tool_calls": []},
                "prompt_eval_count": 8, "eval_count": 2, "total_duration": 100,
                "eval_duration": 50, "load_duration": 10}
        with patch.object(provider, "post", return_value=data) as post:
            response = provider.chat([{"role": "user", "content": "hi"}], [], generation_options={"seed": 7})
        self.assertEqual(response.content, "OK")
        self.assertEqual(response.metrics["eval_count"], 2)
        self.assertEqual(post.call_args.kwargs["json"]["options"]["seed"], 7)

    def test_comparison_rejects_changed_tasks(self):
        report = {"schema_version": 1, "suite_sha256": "a", "task_sha256": {"a": "b"},
                  "repetitions": 3, "summary": []}
        changed = {**report, "task_sha256": {"a": "c"}}
        with self.assertRaisesRegex(ValueError, "not comparable"):
            compare(report, changed)

    def test_decision_requires_aggregate_gain_without_holdout_regression(self):
        def row(task_id, split, passed):
            return {"model": "m", "mode": "agent", "split": split, "task_id": task_id,
                    "passed": passed, "evaluated": 5, "pass_rate": passed / 5,
                    "mean_wall_seconds": 1, "ollama_metric_totals": {"eval_count": 10}}
        baseline = {"schema_version": 2, "suite_sha256": "suite", "task_sha256": {"tasks": "same"},
                    "repetitions": 5, "summary": [row("dev", "development", 1), row("held", "holdout", 4)]}
        candidate = {**baseline, "summary": [row("dev", "development", 3), row("held", "holdout", 4)]}
        self.assertTrue(decision(baseline, candidate)["accepted"])
        regressed = {**baseline, "summary": [row("dev", "development", 4), row("held", "holdout", 3)]}
        outcome = decision(baseline, regressed)
        self.assertFalse(outcome["accepted"])
        self.assertEqual(outcome["pass_delta"], 2)
        self.assertEqual(outcome["holdout_regressions"][0]["task_id"], "held")


if __name__ == "__main__":
    unittest.main()
