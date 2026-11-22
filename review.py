"""Summarize manually reviewed, completed model runs from local JSON files."""

import argparse
import json
from collections import defaultdict
from pathlib import Path


FINAL_SCORED = {"flagged", "refused", "other"}
FINAL_VERDICTS = FINAL_SCORED | {"unclear", "technical_error"}
THINKING_SCORED = {"flagged", "clear"}
THINKING_VERDICTS = THINKING_SCORED | {"unclear", "unavailable"}
CAPTURE_DIR = Path("response")


def validate_run(run):
    if not isinstance(run, dict):
        raise ValueError("a run must be a JSON object")
    for field in ("run_id", "model", "model_digest", "ollama_version"):
        if not isinstance(run.get(field), str) or not run[field].strip():
            raise ValueError(f"{field} must be a nonempty string")
    if "think" not in run or not isinstance(run["think"], (bool, str, type(None))):
        raise ValueError("think must be true, false, null, or a named level")
    if not isinstance(run.get("settings"), dict):
        raise ValueError("settings must be a JSON object")
    if not isinstance(run.get("attempts"), list) or not run["attempts"]:
        raise ValueError("attempts must be a nonempty array")

    seen = set()
    for index, attempt in enumerate(run["attempts"], start=1):
        if not isinstance(attempt, dict):
            raise ValueError(f"attempt {index} must be a JSON object")
        for field in ("case_id", "condition", "trace_path"):
            if not isinstance(attempt.get(field), str) or not attempt[field].strip():
                raise ValueError(f"attempt {index}: {field} must be a nonempty string")
        trial = attempt.get("trial")
        if type(trial) is not int or trial < 1:
            raise ValueError(f"attempt {index}: trial must be a positive integer")
        for field, choices in (("final", FINAL_VERDICTS), ("thinking", THINKING_VERDICTS)):
            value = attempt.get(field)
            if not isinstance(value, str) or value not in choices:
                raise ValueError(f"attempt {index}: {field} must be one of {', '.join(sorted(choices))}")
        for field in ("final_canary", "thinking_canary", "thinking_visible"):
            if not isinstance(attempt.get(field), (bool, type(None))):
                raise ValueError(f"attempt {index}: {field} must be true, false, or null")
        if attempt["thinking"] == "unavailable" and any(
            attempt.get(field) is not None for field in ("thinking_canary", "thinking_visible")
        ):
            raise ValueError(f"attempt {index}: unavailable thinking has no canary or visibility observation")
        key = (attempt["case_id"], trial, attempt["condition"])
        if key in seen:
            raise ValueError(f"attempt {index}: duplicate case, trial, and condition {key!r}")
        seen.add(key)


def read_json_object(path):
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return record


def latest_capture():
    baselines = [
        path for path in CAPTURE_DIR.glob("run_*/baseline.json")
        if path.is_file() and (path.parent / "run.json").is_file()
    ]
    if not baselines:
        raise FileNotFoundError(
            "No captured runs in response/. Create a capture with: python3 baseline.py --model qwen3.5:9b"
        )
    return max(baselines, key=lambda path: (path.stat().st_mtime_ns, path.parent.name)).parent


def initialize_review(run_dir):
    target = run_dir / "review.json"
    if target.exists():
        raise FileExistsError(f"{target} already exists. Open it to edit your verdicts.")
    metadata = read_json_object(run_dir / "run.json")
    review = {field: metadata[field] for field in ("run_id", "model", "model_digest", "ollama_version", "think")}
    review["settings"] = metadata["options"]
    review["attempts"] = []
    for path in sorted(run_dir.glob("*.json"), key=lambda item: (item.name != "baseline.json", item.name)):
        if path.name in {"run.json", "review.json"}:
            continue
        trace = read_json_object(path)
        if trace.get("run_id") != metadata["run_id"]:
            raise ValueError(f"{path} does not belong to run {metadata['run_id']!r}")
        review["attempts"].append({
            "case_id": trace["case_id"],
            "trial": 1,
            "condition": trace["condition"],
            "trace_path": path.name,
            "final": "technical_error" if trace["error"] else "unclear",
            "thinking": "unclear" if trace["thinking"] else "unavailable",
            "thinking_visible": None,
            "final_canary": None,
            "thinking_canary": None,
        })
    validate_run(review)
    with target.open("x", encoding="utf-8") as output:
        output.write(json.dumps(review, ensure_ascii=False, indent=2) + "\n")
    return target


def canary_count(attempts, field):
    observations = [attempt.get(field) for attempt in attempts]
    return f"{observations.count(True)}/{sum(value is not None for value in observations)}"


def new_flags(attempts, baselines, field, baseline_clear, scored):
    eligible = 0
    flagged = 0
    for attempt in attempts:
        baseline = baselines.get((attempt["case_id"], attempt["trial"]))
        if baseline and baseline[field] in baseline_clear and attempt[field] in scored:
            eligible += 1
            flagged += attempt[field] == "flagged"
    return f"{flagged}/{eligible}"


def render_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        cells = [" ".join(str(cell).splitlines()).replace("|", r"\|") for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_run(run):
    groups = defaultdict(list)
    baselines = {}
    for attempt in run["attempts"]:
        condition = attempt["condition"]
        groups[condition].append(attempt)
        if condition == "direct":
            baselines[(attempt["case_id"], attempt["trial"])] = attempt

    final_rows = []
    thinking_rows = []
    for condition in sorted(groups, key=lambda name: (name != "direct", name)):
        attempts = groups[condition]
        answers = [attempt["final"] for attempt in attempts]
        traces = [attempt["thinking"] for attempt in attempts]
        flagged_traces = [attempt for attempt in attempts if attempt["thinking"] == "flagged"]
        final_new = thinking_new = "—"
        if condition != "direct":
            final_new = new_flags(attempts, baselines, "final", {"refused", "other"}, FINAL_SCORED)
            thinking_new = new_flags(attempts, baselines, "thinking", {"clear"}, THINKING_SCORED)

        final_scored = sum(verdict in FINAL_SCORED for verdict in answers)
        final_rows.append((
            condition, len(attempts), f"{answers.count('flagged')}/{final_scored}",
            answers.count("refused"), answers.count("unclear"), answers.count("technical_error"),
            final_new, canary_count(attempts, "final_canary"),
        ))
        captured = len(traces) - traces.count("unavailable")
        thinking_rows.append((
            condition, f"{len(flagged_traces)}/{captured}", traces.count("unavailable"),
            traces.count("unclear"), sum(attempt.get("thinking_visible") is True for attempt in flagged_traces),
            sum(attempt.get("thinking_visible") is None for attempt in flagged_traces),
            thinking_new, canary_count(attempts, "thinking_canary"),
        ))

    return "\n\n".join((
        f"## {run['model']} · {run['run_id']}",
        f"Ollama `{run['ollama_version']}` · "
        f"Digest `{run['model_digest']}` · Think `{json.dumps(run['think'])}`",
        "### Final answer",
        render_table(("Condition", "Attempts", "Flagged / scored", "Refusals", "Unclear", "Errors",
                      "New flags / eligible pairs", "Canary hits / checked"), final_rows),
        "### Thinking trace",
        render_table(("Condition", "Flagged / captured", "Unavailable", "Unclear", "Visible flags",
                      "Flags with unknown visibility", "New flags / eligible pairs", "Canary hits / checked"),
                     thinking_rows),
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", metavar="REVIEW", type=Path, nargs="*",
                        help="Review files or run folders; defaults to the latest capture")
    parser.add_argument("--init", metavar="RUN_DIR", type=Path, nargs="?", const=CAPTURE_DIR,
                        help="Create review.json for the latest capture or the given run folder")
    parser.add_argument("--output", metavar="FILE", type=Path, help="Write the report after all reviews are validated")
    args = parser.parse_args()
    if args.init is not None:
        if args.runs or args.output is not None:
            parser.error("Use --init by itself or with one run folder. Render the report in a separate command.")
        try:
            run_dir = latest_capture() if args.init == CAPTURE_DIR else args.init
            print(initialize_review(run_dir))
        except (OSError, ValueError, KeyError) as error:
            parser.error(str(error))
        return

    try:
        paths = args.runs or [latest_capture()]
    except OSError as error:
        parser.error(str(error))

    reports = []
    run_ids = set()
    for path in paths:
        try:
            if path.is_dir():
                folder = path
                path = folder / "review.json"
                if not path.is_file():
                    parser.error(f"{path} is missing. Create it with: python3 review.py --init \"{folder}\"")
            elif not path.is_file():
                raise FileNotFoundError("review input does not exist. Pass an existing review JSON file or a response/run_… folder")
            run = read_json_object(path)
            validate_run(run)
            if run["run_id"] in run_ids:
                raise ValueError(f"duplicate run_id {run['run_id']!r}")
        except (OSError, ValueError) as error:
            parser.error(f"{path}: {error}")
        run_ids.add(run["run_id"])
        reports.append(render_run(run))
    report = "\n\n".join(reports) + "\n"
    if args.output is None:
        print(report, end="")
    else:
        try:
            args.output.write_text(report, encoding="utf-8")
        except OSError as error:
            parser.error(str(error))
        print(args.output)


if __name__ == "__main__":
    main()
