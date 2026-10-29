import os
from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass
class User:
    email: str
    role: str
    mode: str

    @property
    def is_admin(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "Guest"

    @property
    def initials(self) -> str:
        return "G"


GUEST = User("guest", "viewer", "public")


def public_view() -> bool:
    return True


def oauth_config():
    return None


def session_secret() -> str:
    return os.environ["BI_SESSION_SECRET"]


def current_user(request: Request) -> User:
    return GUEST


def require_user(request: Request) -> User:
    return GUEST


def require_admin(request: Request) -> User:
    raise HTTPException(status_code=403, detail="This is a read-only copy.")


def csrf_token(request: Request) -> str:
    return ""


def check_csrf(request: Request, token) -> None:
    raise HTTPException(status_code=403, detail="This is a read-only copy.")
