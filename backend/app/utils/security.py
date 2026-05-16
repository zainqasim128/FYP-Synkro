"""
Security utilities for password hashing and JWT token management.
"""
from datetime import datetime, timedelta
from typing import Any, Optional
import jwt
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext

from app.config import settings

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """
    Hash a plain password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password from database

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Data to encode in the token (usually {"sub": user_id})
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT refresh token.

    Args:
        data: Data to encode in the token (usually {"sub": user_id})
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT refresh token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def verify_token(token: str, token_type: str = "access") -> Optional[dict[str, Any]]:
    """
    Verify and decode a JWT token.

    Args:
        token: JWT token to verify
        token_type: Expected token type ("access" or "refresh")

    Returns:
        Decoded token payload if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

        # Check token type
        if payload.get("type") != token_type:
            return None

        return payload
    except (InvalidTokenError, Exception):
        return None


def decode_token(token: str) -> Optional[str]:
    """
    Decode a token and return the user ID.

    Args:
        token: JWT token

    Returns:
        User ID (sub claim) if valid, None otherwise
    """
    payload = verify_token(token)
    if payload is None:
        return None

    return payload.get("sub")


# ------------------------------------------------------------
# Fernet encryption for sensitive DB fields (OAuth tokens, API credentials).
# Uses FERNET_KEY from .env — a dedicated key separate from the JWT SECRET_KEY
# so rotating one does not break the other.
# Works identically for Neon (cloud) and local PostgreSQL.

from cryptography.fernet import Fernet, InvalidToken
from base64 import urlsafe_b64encode
import hashlib


def _build_fernet() -> Fernet:
    """Return a Fernet instance, preferring the dedicated FERNET_KEY."""
    if settings.FERNET_KEY:
        return Fernet(settings.FERNET_KEY.encode())
    # Derive from SECRET_KEY as a fallback so existing encrypted data keeps working
    key_material = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(urlsafe_b64encode(key_material))


_fernet = _build_fernet()


def encrypt_value(plain: str) -> str:
    """Encrypt a string before storing in the database."""
    if not plain:
        return plain
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_value(cipher: str) -> str:
    """Decrypt a value stored by :func:`encrypt_value`.

    Falls back to returning the raw value so rows that were saved before
    encryption was enabled (e.g. existing Gmail app passwords) continue to
    work without a manual migration.
    """
    if not cipher:
        return cipher
    try:
        return _fernet.decrypt(cipher.encode()).decode()
    except (InvalidToken, Exception):
        # Value was stored in plaintext — return it as-is
        return cipher
