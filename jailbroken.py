
"""Read prompt files and send them directly to the model."""

import argparse
import json
from pathlib import Path

from baseline import CAPTURE_DIR, record_attempt

FIXTURES = Path(__file__).resolve().parent / "jailbreaks"


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--run-dir",
        type=Path,
        help="Run folder; defaults to the latest run"
    )

    parser.add_argument(
        "fixtures",
        nargs="*",
        help="TXT filenames; defaults to all files in jailbreaks/"
    )

    args = parser.parse_args()

    # Automatically select the latest run if none is provided
    run_dir = args.run_dir

    if run_dir is None:
        runs = list(CAPTURE_DIR.glob("run_*/run.json"))

        if not runs:
            parser.error("No previous runs found. Run baseline.py first.")

        run_dir = max(runs, key=lambda p: p.stat().st_mtime).parent

    # Read run configuration
    run = json.loads((run_dir / "run.json").read_text())

    # Use provided TXT files, or all TXT files if none were provided
    files = args.fixtures or [
        path.name for path in sorted(FIXTURES.glob("*.txt"))
    ]

    if not files:
        parser.error(f"No TXT files found in {FIXTURES}")

    # Read and send prompts
    for filename in files:
        file_path = FIXTURES / filename

        if not file_path.is_file() or file_path.suffix.lower() != ".txt":
            parser.error(f"Invalid fixture file: {filename}")

        prompt = file_path.read_text(encoding="utf-8")

        record_attempt(
            run_dir,
            run,
            file_path.stem,
            prompt
        )


if __name__ == "__main__":
    main()
