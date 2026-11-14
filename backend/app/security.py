import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings

_hasher = PasswordHasher()
# Verified against when the email is unknown, so both cases take the same time.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        # An empty hash (e.g. an HOD without a portal login) must never match, not even the dummy's password.
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except (VerificationError, InvalidHashError):
        return False


def new_token() -> tuple[str, str]:
    """Returns (token for the client, hash to store)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(mobile: str, code: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{mobile}:{code}".encode(), hashlib.sha256).hexdigest()


def otp_matches(mobile: str, code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(mobile, code), code_hash)


def _fernet() -> Fernet:
    # Derived from SECRET_KEY: changing that key means saved secrets must be entered again.
    digest = hashlib.sha256(f"{get_settings().secret_key}|stored-secrets".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    """None if it can't be read (e.g. SECRET_KEY changed since it was saved)."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def file_link_signature(version_id: str, name: str, expires: int) -> str:
    """Signs a project-file download link, so it opens in a browser without a login and stops working later."""
    key = hashlib.sha256(b"file-link:" + get_settings().secret_key.encode()).digest()
    return hmac.new(key, f"{version_id}:{name}:{expires}".encode(), hashlib.sha256).hexdigest()


def webhook_signature(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def valid_webhook_signature(body: bytes, signature: str | None) -> bool:
    secret = get_settings().salesforce_webhook_secret
    if not secret or not signature:
        return False
    return hmac.compare_digest(webhook_signature(body, secret), signature.strip().lower())
