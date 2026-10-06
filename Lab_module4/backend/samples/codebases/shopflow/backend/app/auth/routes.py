"""Auth endpoints: register, login, current user."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ..db import get_session
from ..orders.models import User
from .dependencies import get_current_user
from .service import AuthError, AuthService

router = APIRouter()


class Credentials(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=201)
def register(body: Credentials, session: Session = Depends(get_session)) -> dict:
    user = AuthService(session).register(body.email, body.password)
    return {"id": user.id, "email": user.email}


@router.post("/login")
def login(body: Credentials, session: Session = Depends(get_session)) -> dict:
    try:
        token = AuthService(session).login(body.email, body.password)
    except AuthError as err:
        raise HTTPException(401, str(err)) from err
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"id": user.id, "email": user.email}
