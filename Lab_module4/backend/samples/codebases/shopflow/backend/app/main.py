"""FastAPI application: wires the routers together."""

from fastapi import FastAPI

from .auth.routes import router as auth_router
from .db import engine
from .orders.models import Base
from .orders.routes import router as orders_router

app = FastAPI(title="Shopflow API", version="1.4.0")
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(orders_router, prefix="/orders", tags=["orders"])


@app.on_event("startup")
def create_tables() -> None:
    """Create missing tables on startup (migrations are out of scope for this demo)."""
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
