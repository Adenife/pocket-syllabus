import secrets
import sqlite3
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.core.security import bearer, current_owner, get_context, password_hash, verify_password, token_hash
from app.schemas.user import Credentials

router = APIRouter(prefix='/auth', tags=['accounts'])

@router.get('/mode')
def mode(request: Request):
    settings = get_context(request).settings
    return {'auth_enabled': settings.auth_enabled, 'registration_enabled': settings.registration_enabled,
            'max_upload_bytes': settings.max_upload_bytes}

@router.post('/register', status_code=201)
def register(payload: Credentials, request: Request):
    context = get_context(request)
    if not context.settings.auth_enabled or not context.settings.registration_enabled:
        raise HTTPException(403, 'Registration is disabled')
    try:
        with context.db.connect() as conn:
            conn.execute('INSERT INTO users VALUES (?,?,?,?)', (str(uuid.uuid4()), payload.username, password_hash(payload.password), time.time()))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, 'Username unavailable') from exc
    return {'username': payload.username}

@router.post('/login')
def login(payload: Credentials, request: Request):
    context = get_context(request)
    if not context.settings.auth_enabled:
        raise HTTPException(403, 'Accounts are disabled in local mode')
    with context.db.connect() as conn:
        row = conn.execute('SELECT * FROM users WHERE username=?', (payload.username,)).fetchone()
        # A dummy hash verification reduces username timing differences.
        stored = row['password_hash'] if row else '00' * 16 + ':' + '00' * 64
        if not verify_password(payload.password, stored) or not row:
            raise HTTPException(401, 'Invalid username or password')
        token = secrets.token_urlsafe(32)
        conn.execute('DELETE FROM tokens WHERE expires_at<?', (time.time(),))
        conn.execute('INSERT INTO tokens VALUES (?,?,?)', (token_hash(token), row['id'], time.time() + 86400 * 7))
    return {'access_token': token, 'token_type': 'bearer', 'expires_in': 86400 * 7}

@router.post('/logout', status_code=204)
def logout(request: Request, owner: str = Depends(current_owner), credential=Depends(bearer)):
    if credential:
        with get_context(request).db.connect() as conn:
            conn.execute('DELETE FROM tokens WHERE hash=? AND owner_id=?', (token_hash(credential.credentials), owner))
    return Response(status_code=204)
