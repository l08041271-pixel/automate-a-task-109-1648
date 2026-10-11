#!/usr/bin/env python
"""Process due follow-up jobs.

Designed to be run by GitHub Actions on a schedule (or manually):

    python scripts/run_followups.py

It only ever creates DRAFTED messages — no customer is messaged by this script.
Exit codes: 0 = ok, 1 = unexpected error.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services import followups  # noqa: E402


def main() -> int:
    configure_logging()
    with SessionLocal() as db:
        report = followups.process_due_jobs(db)
        db.commit()
    print(
        json.dumps(
            {
                "processed": report.processed,
                "drafted": report.drafted,
                "skipped": report.skipped,
                "cancelled": report.cancelled,
                "failed": report.failed,
                "reasons": report.reasons,
                "note": "drafts only; nothing was sent to any customer",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
