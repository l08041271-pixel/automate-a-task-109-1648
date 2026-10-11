#!/usr/bin/env python
"""Copy the GitHub Actions workflows into ``.github/workflows/``.

GitHub forbids App/CI tokens from writing inside ``.github/workflows/``, so the
workflow files live in ``ci/github-actions/`` and are installed by a human (or
a token that has the ``workflows`` permission).

    python scripts/install_workflows.py
"""
from __future__ import annotations

import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ci" / "github-actions"
TARGET = ROOT / ".github" / "workflows"


def main() -> int:
    if not SOURCE.is_dir():
        print(f"ERROR: {SOURCE} not found")
        return 1

    TARGET.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted(SOURCE.glob("*.yml")):
        destination = TARGET / path.name
        shutil.copyfile(path, destination)
        print(f"installed {destination.relative_to(ROOT)}")
        copied += 1

    print(f"\n{copied} workflow(s) installed. Now run:")
    print("  git add .github/workflows && git commit -m 'chore: enable scheduled workflows'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
