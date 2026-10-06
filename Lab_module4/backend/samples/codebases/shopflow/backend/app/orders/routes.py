"""Order endpoints (all require a logged-in user)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..config import get_settings
from ..db import get_session
from ..inventory.stock import LowStockError
from ..payments.client import PaymentClient
from .models import Order, User
from .service import OrderService

router = APIRouter()


class Item(BaseModel):
    sku: str
    quantity: int = Field(gt=0, le=20)
    unit_price: float = Field(gt=0)


class OrderRequest(BaseModel):
    items: list[Item] = Field(min_length=1, max_length=50)
    discount_code: str | None = None


def order_service(session: Session = Depends(get_session)) -> OrderService:
    settings = get_settings()
    return OrderService(session, PaymentClient(settings.payment_api_url, settings.payment_api_key))


@router.post("", status_code=201)
def create_order(
    body: OrderRequest,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(order_service),
) -> dict:
    """Place an order for the current user. 409 when an item is out of stock,
    402 when the payment is declined."""
    try:
        order = service.place_order(user, [i.model_dump() for i in body.items], body.discount_code)
    except LowStockError as err:
        raise HTTPException(409, str(err)) from err
    if order.status == "payment_failed":
        raise HTTPException(402, "Payment declined")
    return {"id": order.id, "status": order.status, "total": str(order.total)}


@router.get("/{order_id}")
def get_order(
    order_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)
) -> dict:
    order = session.get(Order, order_id)
    if order is None or order.user_id != user.id:
        raise HTTPException(404, "Order not found")
    return {"id": order.id, "status": order.status, "total": str(order.total)}


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(order_service),
) -> dict:
    order = service.session.get(Order, order_id)
    if order is None or order.user_id != user.id:
        raise HTTPException(404, "Order not found")
    return {"id": order.id, "status": service.cancel_order(order).status}
