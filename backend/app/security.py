from __future__ import annotations

import datetime as dt

import bcrypt
import jwt

from app.config import settings

# bcrypt silently ignores anything past 72 bytes; truncate explicitly so a
# long password can never be mistaken for a stronger one than it is.
_BCRYPT_MAX_BYTES = 72


def _prepare(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database -- treat as a failed login, not a 500.
        return False


def create_access_token(subject: str, role: str) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``."""
    expires_in = settings.access_token_expire_minutes * 60
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
