"""Compare two benchmark reports without changing either artifact."""

import argparse
import json
from pathlib import Path


def compare(baseline, candidate):
    if baseline.get("schema_version") != candidate.get("schema_version"):
        raise ValueError("Report schema versions differ")
    if (baseline.get("suite_sha256") != candidate.get("suite_sha256")
            or baseline.get("task_sha256") != candidate.get("task_sha256")
            or baseline.get("repetitions") != candidate.get("repetitions")):
        raise ValueError("Task suite or repetition count differs; results are not comparable")
    key = lambda row: (row["model"], row["mode"], row["split"], row["task_id"])
    left = {key(row): row for row in baseline["summary"]}
    right = {key(row): row for row in candidate["summary"]}
    if set(left) != set(right):
        raise ValueError("Models or tasks differ; results are not directly comparable")
    result = []
    for identity in sorted(left):
        before, after = left[identity], right[identity]
        if before["evaluated"] != after["evaluated"]:
            raise ValueError("Skipped counts differ; review before comparison")
        b_rate, a_rate = before["pass_rate"], after["pass_rate"]
        result.append({
            "model": identity[0], "mode": identity[1], "split": identity[2], "task_id": identity[3],
            "pass_rate_delta": None if b_rate is None else a_rate - b_rate,
            "mean_wall_seconds_delta": after["mean_wall_seconds"] - before["mean_wall_seconds"],
            "eval_count_delta": (
                after["ollama_metric_totals"]["eval_count"] - before["ollama_metric_totals"]["eval_count"]
                if before["ollama_metric_totals"]["eval_count"] is not None
                and after["ollama_metric_totals"]["eval_count"] is not None else None),
        })
    return result


def decision(baseline, candidate):
    """Apply the predeclared quality gate to comparable N-repeat reports."""
    deltas = compare(baseline, candidate)
    regressions = [row for row in deltas if row["split"] == "holdout"
                   and row["pass_rate_delta"] is not None and row["pass_rate_delta"] < 0]
    before = sum(row["passed"] for row in baseline["summary"])
    after = sum(row["passed"] for row in candidate["summary"])
    coverage_before = sum(row["evaluated"] for row in baseline["summary"])
    coverage_after = sum(row["evaluated"] for row in candidate["summary"])
    return {"accepted": after > before and not regressions and coverage_after >= coverage_before,
            "passed_before": before, "passed_after": after, "pass_delta": after - before,
            "evaluated_before": coverage_before, "evaluated_after": coverage_after,
            "holdout_regressions": regressions}


def main():
    parser = argparse.ArgumentParser(description="Compare two frozen benchmark reports")
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    args = parser.parse_args()
    left = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    right = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    for row in compare(left, right):
        delta = row["pass_rate_delta"]
        print(f"{row['model']} {row['mode']} {row['split']} {row['task_id']}: "
              f"pass_delta={delta:+.1%}" if delta is not None else
              f"{row['model']} {row['mode']} {row['split']} {row['task_id']}: skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
