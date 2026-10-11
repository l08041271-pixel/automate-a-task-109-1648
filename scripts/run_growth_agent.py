#!/usr/bin/env python
"""Run the AI Growth Agent (recommendation-only) on a schedule.

    python scripts/run_growth_agent.py --days 7

Writes an automation_runs record and prints the recommendations as JSON.
Performs no consequential action whatsoever.
Exit codes: 0 = ok, 1 = unexpected error.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.logging import configure_logging  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services import growth_agent  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the growth agent (recommendation only)")
    parser.add_argument("--days", type=int, default=7, help="analysis window in days")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args()

    configure_logging()
    with SessionLocal() as db:
        report = growth_agent.run_analysis(db, days=args.days)
        db.commit()

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, default=str))
    else:
        print(report.summary_text)
        print()
        for rec in report.recommendations:
            flag = " [NEEDS AUTHORIZATION]" if rec.requires_authorization else ""
            print(f"- ({rec.severity}) {rec.title}{flag}")
            print(f"    evidence: {json.dumps(rec.evidence, default=str)}")
            print(f"    action:   {rec.suggested_action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
