"""Stock reservation. Quantities live in the `stock` table, one row per SKU."""

from sqlalchemy import text
from sqlalchemy.orm import Session


class LowStockError(Exception):
    """Raised when an item cannot be reserved because not enough units are left."""


def reserve_stock(session: Session, items: list[dict]) -> None:
    """Take the requested quantities out of stock, all or nothing.

    Each SKU is decremented with a conditional UPDATE, so two concurrent orders can never
    take the last unit twice. If any item is short, everything reserved so far is put
    back and LowStockError names the SKU.
    """
    reserved: list[dict] = []
    for item in items:
        result = session.execute(
            text("UPDATE stock SET quantity = quantity - :q WHERE sku = :sku AND quantity >= :q"),
            {"q": item["quantity"], "sku": item["sku"]},
        )
        if result.rowcount == 0:
            release_stock(session, reserved)
            raise LowStockError(f"Not enough stock for {item['sku']}")
        reserved.append(item)


def release_stock(session: Session, items: list[dict]) -> None:
    """Return quantities to stock (after a failed payment or a cancellation)."""
    for item in items:
        session.execute(
            text("UPDATE stock SET quantity = quantity + :q WHERE sku = :sku"),
            {"q": item["quantity"], "sku": item["sku"]},
        )
