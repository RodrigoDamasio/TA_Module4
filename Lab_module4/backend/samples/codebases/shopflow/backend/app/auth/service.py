"""User registration and login."""

from sqlalchemy.orm import Session

from ..orders.models import User
from .security import create_access_token, hash_password, verify_password


class AuthError(Exception):
    """Wrong email or password (the message never says which one)."""


class AuthService:
    """Registers users and exchanges credentials for access tokens."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def register(self, email: str, password: str) -> User:
        if len(password) < 10:
            raise ValueError("Passwords need at least 10 characters.")
        user = User(email=email.lower(), password_hash=hash_password(password))
        self.session.add(user)
        self.session.commit()
        return user

    def login(self, email: str, password: str) -> str:
        """Check the credentials and return a signed JWT access token."""
        user = self.session.query(User).filter_by(email=email.lower()).one_or_none()
        if user is None or not verify_password(password, user.password_hash):
            raise AuthError("Invalid email or password.")
        return create_access_token(user.id)
