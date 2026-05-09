#!/usr/bin/env python3
"""Upsert the wedding guest list from CSV into Supabase.

CSV columns: name, phone, num_allowed, guests
  - phone:       any human-readable form; normalized to E.164
  - num_allowed: positive int; defaults to len(guests) or 1
  - guests:      ';'-separated names (CSV is comma-delimited, hence ';')
  - name:        optional; used only for log labels
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from _phone import normalize_phone

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GUESTS = SCRIPT_DIR / "guests.csv"
REQUIRED_COLUMNS = {"phone", "num_allowed", "guests"}


def parse_guests(field: str) -> list[str]:
    return [g.strip() for g in (field or "").split(";") if g.strip()]


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            sys.exit(
                f"error: {path} must have columns {sorted(REQUIRED_COLUMNS)} "
                f"(found {reader.fieldnames})"
            )
        rows: list[dict] = []
        for i, row in enumerate(reader, start=2):
            raw_phone = (row.get("phone") or "").strip()
            if not raw_phone:
                continue
            phone = normalize_phone(raw_phone)
            if phone is None:
                print(f"  skip row {i}: cannot parse phone {raw_phone!r}")
                continue

            guests = parse_guests(row.get("guests") or "")
            raw_allowed = (row.get("num_allowed") or "").strip()
            try:
                num_allowed = int(raw_allowed) if raw_allowed else max(len(guests), 1)
            except ValueError:
                print(f"  skip row {i}: num_allowed {raw_allowed!r} not an int")
                continue
            if num_allowed < 1:
                print(f"  skip row {i}: num_allowed must be >= 1")
                continue

            rows.append({
                "phone": phone,
                "guests": guests,
                "num_allowed": num_allowed,
                "_label": (row.get("name") or "").strip(),
            })
    return rows


def upsert(url: str, key: str, rows: list[dict]) -> None:
    payload = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    resp = requests.post(
        f"{url}/rest/v1/guest_list",
        params={"on_conflict": "phone"},
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        json=payload,
        timeout=30,
    )
    if not resp.ok:
        sys.exit(f"error: Supabase returned {resp.status_code}: {resp.text}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="parse CSV, print summary, do not call Supabase")
    parser.add_argument("--guests", type=Path, default=DEFAULT_GUESTS, help=f"path to guest CSV (default: {DEFAULT_GUESTS})")
    args = parser.parse_args()

    load_dotenv(SCRIPT_DIR.parent / ".env")
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not args.guests.exists():
        sys.exit(f"error: guest file not found: {args.guests} (copy guests.csv.example to guests.csv)")

    rows = load_rows(args.guests)
    print(f"Guest file:  {args.guests}")
    print(f"Parsed rows: {len(rows)}")
    for r in rows:
        label = f" ({r['_label']})" if r["_label"] else ""
        print(f"  {r['phone']}{label}  allowed={r['num_allowed']}  guests={r['guests']}")

    if not rows:
        print("Nothing to upload.")
        return 0

    if args.dry_run:
        print("\nDRY RUN — not calling Supabase.")
        return 0

    if not url or not key:
        sys.exit("error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")

    answer = input(f"\nUpsert {len(rows)} rows into {url}? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return 1

    upsert(url, key, rows)
    print(f"Done. Upserted {len(rows)} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
