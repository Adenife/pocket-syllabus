"""Passwords, opaque bearer sessions, and optional encrypted storage."""
import hashlib
import hmac
import secrets
import time
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)
LOCAL_OWNER = "local"

class Codec:
    def __init__(self, key=""):
        self.key = key
        if key:
            from cryptography.fernet import Fernet
            self.fernet = Fernet(key.encode())
    def encode(self, data: bytes) -> bytes:
        return self.fernet.encrypt(data) if self.key else data
    def decode(self, data: bytes) -> bytes:
        return self.fernet.decrypt(data) if self.key else data


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    salt, expected = stored.split(":")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(actual.hex(), expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_context(request: Request):
    return request.app.state.context


def current_owner(request: Request, credential: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    context = get_context(request)
    if not context.settings.auth_enabled:
        return LOCAL_OWNER
    if credential:
        with context.db.connect() as conn:
            token = conn.execute("SELECT owner_id FROM tokens WHERE hash=? AND expires_at>?",
                                 (token_hash(credential.credentials), time.time())).fetchone()
        if token:
            return token['owner_id']
    raise HTTPException(401, "Sign in to access your library", headers={"WWW-Authenticate": "Bearer"})
