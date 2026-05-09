#!/usr/bin/env python3
"""Send the Farbeen & Tommy save-the-date SMS via Twilio."""

import argparse
import csv
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from _phone import normalize_phone

MESSAGE = (
    "Mr. Mohammad Rahman and Mrs. Habiba Rahman are excited to invite you to "
    "celebrate the wedding of their daughter, Farbeen Safa, and Tommy Mulc. "
    "Kindly save the date for November 21st, 2026 in Dallas, TX. Formal "
    "invitation and RSVPs to follow. Please visit the link below for more "
    "details.\n\nhttps://nov21.party"
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GUESTS = SCRIPT_DIR / "test_list.csv"
SENT_LOG = SCRIPT_DIR / "sent.log"
SEND_DELAY_SECONDS = 35


def load_sent() -> set[str]:
    if not SENT_LOG.exists():
        return set()
    return {line.strip() for line in SENT_LOG.read_text().splitlines() if line.strip()}


def record_sent(number: str) -> None:
    with SENT_LOG.open("a") as f:
        f.write(number + "\n")
        f.flush()


def load_guests(path: Path) -> list[tuple[str, str]]:
    """Return (name, normalized_phone) tuples, skipping unparseable rows."""
    results: list[tuple[str, str]] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "phone" not in reader.fieldnames:
            sys.exit(f"error: {path} must have a 'phone' column")
        for i, row in enumerate(reader, start=2):
            raw = (row.get("phone") or "").strip()
            name = (row.get("name") or "").strip()
            if not raw:
                continue
            normalized = normalize_phone(raw)
            if normalized is None:
                print(f"  skip row {i}: could not parse phone {raw!r} ({name})")
                continue
            results.append((name, normalized))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print what would send, do not call Twilio")
    parser.add_argument("--guests", type=Path, default=DEFAULT_GUESTS, help=f"path to guest CSV (default: {DEFAULT_GUESTS})")
    parser.add_argument("--limit", type=int, default=None, help="only process first N unsent guests")
    args = parser.parse_args()

    load_dotenv(SCRIPT_DIR.parent / ".env")
    api_key = os.environ.get("TELNYX_API_KEY", "")
    from_number = os.environ.get("TELNYX_FROM_NUMBER", "")

    if not args.dry_run:
        missing = [k for k, v in [("TELNYX_API_KEY", api_key), ("TELNYX_FROM_NUMBER", from_number)] if not v]
        if missing:
            sys.exit(f"error: missing env vars: {', '.join(missing)} (see .env.example)")
        if normalize_phone(from_number) is None:
            sys.exit(f"error: TELNYX_FROM_NUMBER {from_number!r} is not a valid E.164 number")

    if not args.guests.exists():
        sys.exit(f"error: guest file not found: {args.guests} (copy guests.csv.example to guests.csv)")

    guests = load_guests(args.guests)
    sent = load_sent()
    pending = [(n, p) for n, p in guests if p not in sent]
    if args.limit is not None:
        pending = pending[: args.limit]

    print(f"Guest list:      {args.guests}")
    print(f"Total rows:      {len(guests)}")
    print(f"Already sent:    {len(guests) - len([p for _, p in guests if p not in sent])}")
    print(f"To send:         {len(pending)}")
    print(f"From:            {from_number or '(unset)'}")
    print(f"Message:\n  {MESSAGE}\n")

    if not pending:
        print("Nothing to send.")
        return 0

    if args.dry_run:
        print("DRY RUN — would send to:")
        for name, phone in pending:
            label = f" ({name})" if name else ""
            print(f"  {phone}{label}")
        return 0

    answer = input(f"Send to {len(pending)} numbers? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return 1

    from telnyx import Telnyx, TelnyxError

    client = Telnyx(api_key=api_key)
    ok = 0
    fail = 0
    for name, phone in pending:
        label = f" ({name})" if name else ""
        try:
            client.messages.send(from_=from_number, to=phone, text=MESSAGE)
            record_sent(phone)
            ok += 1
            print(f"  ok  {phone}{label}")
        except TelnyxError as e:
            fail += 1
            print(f"  ERR {phone}{label}: {e}")
        time.sleep(SEND_DELAY_SECONDS)

    print(f"\nDone. sent={ok} failed={fail}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
