"""Billing: invoices and late fees for the mini project used by the E2E tests."""


def late_fee(amount_cents: int, days_late: int) -> int:
    """2 % per started week late, capped at 20 %."""
    weeks = (days_late + 6) // 7
    return min(amount_cents * 2 * weeks // 100, amount_cents // 5)


class InvoiceService:
    def __init__(self, repo):
        self.repo = repo

    def issue(self, customer_id: str, amount_cents: int) -> str:
        invoice_id = self.repo.next_id()
        self.repo.save(invoice_id, customer_id, amount_cents)
        return invoice_id
