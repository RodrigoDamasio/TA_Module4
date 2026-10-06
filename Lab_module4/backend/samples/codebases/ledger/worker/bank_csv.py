"""Parser for the bank's daily statement (CSV: date,amount,reference)."""

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class BankLine:
    date: str
    amount_cents: int
    reference: str


def parse_bank_statement(path: Path) -> list[BankLine]:
    """Read the statement and convert decimal amounts ("12.50") to integer cents."""
    with path.open(newline="") as handle:
        return [
            BankLine(row["date"], int(Decimal(row["amount"]) * 100), row["reference"].strip())
            for row in csv.DictReader(handle)
        ]
