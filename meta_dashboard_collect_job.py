import argparse
import json
import os
import traceback
from datetime import datetime
from pathlib import Path

from meta_dashboard_pipeline import collect_to_db


WORKDIR = Path(__file__).resolve().parent
STATUS_PATH = WORKDIR / "collect_job_status.json"


def write_status(payload):
    STATUS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-per-category", type=int, default=100)
    args = parser.parse_args()
    started_at = now_iso()

    write_status(
        {
            "status": "running",
            "pid": os.getpid(),
            "started_at": started_at,
            "finished_at": None,
            "summary": None,
            "error": None,
        }
    )

    try:
        summary = collect_to_db(limit_per_category=args.limit_per_category)
        write_status(
            {
                "status": "done",
                "pid": os.getpid(),
                "started_at": started_at,
                "finished_at": now_iso(),
                "summary": summary,
                "error": None,
            }
        )
    except Exception:
        write_status(
            {
                "status": "failed",
                "pid": os.getpid(),
                "started_at": started_at,
                "finished_at": now_iso(),
                "summary": None,
                "error": traceback.format_exc(),
            }
        )
        raise


if __name__ == "__main__":
    main()
