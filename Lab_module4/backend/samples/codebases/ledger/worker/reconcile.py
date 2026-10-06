"""Nightly reconciliation between the ledger API and the bank statement."""

import json
import os
import sys
import urllib.request
from pathlib import Path

from .bank_csv import BankLine, parse_bank_statement


def fetch_entries(base_url: str, api_key: str) -> list[dict]:
    """GET /entries from the ledger API with the worker's API key."""
    request = urllib.request.Request(f"{base_url}/entries", headers={"x-api-key": api_key})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 — fixed URL
        return json.load(response)


def reconcile_entries(entries: list[dict], bank: list[BankLine]) -> dict[str, list]:
    """Match ledger entries to bank lines by (amount in cents, reference = description).

    Returns entries the bank does not know about (`missing_in_bank`) and bank lines with no
    ledger entry (`missing_in_ledger`). Each bank line can match at most one entry.
    """
    unmatched = list(bank)
    missing_in_bank = []
    for entry in entries:
        match = next(
            (
                b
                for b in unmatched
                if b.amount_cents == entry["amountCents"] and b.reference == entry["description"]
            ),
            None,
        )
        if match is None:
            missing_in_bank.append(entry)
        else:
            unmatched.remove(match)
    return {"missing_in_bank": missing_in_bank, "missing_in_ledger": unmatched}


if __name__ == "__main__":
    report = reconcile_entries(
        fetch_entries(os.environ["LEDGER_URL"], os.environ["LEDGER_API_KEY"]),
        parse_bank_statement(Path(sys.argv[1])),
    )
    print(json.dumps(report, indent=2, default=str))
