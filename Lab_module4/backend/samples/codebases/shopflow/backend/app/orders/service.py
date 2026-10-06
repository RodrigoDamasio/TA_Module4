"""Order placement: stock, discounts, payment, confirmation."""

from decimal import Decimal

from sqlalchemy.orm import Session

from ..inventory.stock import release_stock, reserve_stock
from ..notifications.email import send_order_confirmation
from ..payments.client import PaymentClient, PaymentError
from .models import Order, OrderItem, OrderStatus, User


def apply_discount(subtotal: Decimal, code: str | None) -> Decimal:
    """Apply a discount code to a subtotal.

    WELCOME10 takes 10% off; FREESHIP removes the 5.00 shipping fee; anything else is
    ignored. The result is never negative and is rounded to cents.
    """
    shipping = Decimal("5.00")
    if code == "WELCOME10":
        total = subtotal * Decimal("0.90") + shipping
    elif code == "FREESHIP":
        total = subtotal
    else:
        total = subtotal + shipping
    return max(total, Decimal("0")).quantize(Decimal("0.01"))


class OrderService:
    """Places and cancels orders. Talks to stock, the payment gateway and email."""

    def __init__(self, session: Session, payments: PaymentClient) -> None:
        self.session = session
        self.payments = payments

    def place_order(self, user: User, items: list[dict], discount_code: str | None) -> Order:
        """Reserve stock, charge the card, and save the order.

        If the charge fails, the reserved stock is released and the order is stored with
        status PAYMENT_FAILED so support can see the attempt.
        """
        reserve_stock(self.session, items)
        subtotal = sum(Decimal(str(i["unit_price"])) * i["quantity"] for i in items)
        total = apply_discount(subtotal, discount_code)
        order = Order(user_id=user.id, total=total, discount_code=discount_code)
        order.items = [OrderItem(**item) for item in items]
        try:
            order.payment_id = self.payments.charge(amount=total, customer_email=user.email)
            order.status = OrderStatus.PAID
        except PaymentError:
            release_stock(self.session, items)
            order.status = OrderStatus.PAYMENT_FAILED
        self.session.add(order)
        self.session.commit()
        if order.status is OrderStatus.PAID:
            send_order_confirmation(user.email, order)
        return order

    def cancel_order(self, order: Order) -> Order:
        """Cancel a paid order: refund the payment and put the items back in stock."""
        if order.status is not OrderStatus.PAID:
            raise ValueError(f"Only paid orders can be cancelled (status: {order.status}).")
        self.payments.refund(order.payment_id or "", amount=order.total)
        release_stock(self.session, [{"sku": i.sku, "quantity": i.quantity} for i in order.items])
        order.status = OrderStatus.REFUNDED
        self.session.commit()
        return order
