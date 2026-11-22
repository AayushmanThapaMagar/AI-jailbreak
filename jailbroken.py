"""Read prompt files and send them directly to the model."""

import argparse
import json
from pathlib import Path

from baseline import CAPTURE_DIR, record_attempt

FIXTURES = Path(__file__).resolve().parent / "jailbreaks"


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "run_dir",
        type=Path,
        nargs="?",
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
        run_dir = max(runs, key=lambda p: p.stat().st_mtime).parent

    # Read run configuration
    run = json.loads((run_dir / "run.json").read_text())

    # Select fixture files
    files = args.fixtures or [
        path.name for path in sorted(FIXTURES.glob("*.txt"))
    ]

    # Read and send prompts
    for filename in files:
        prompt = (FIXTURES / filename).read_text(encoding="utf-8")

        record_attempt(
            run_dir,
            run,
            Path(filename).stem,
            prompt
        )


if __name__ == "__main__":
    main()