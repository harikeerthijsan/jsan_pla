import os, hmac, hashlib, secrets, base64, json, time
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from .db import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)
ITERATIONS = 210_000

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
    return f'pbkdf2_sha256${ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(dk).decode()}'

def verify_password(password: str, stored: str) -> bool:
    try:
        alg, iterations, salt64, dk64 = stored.split('$', 3)
        if alg != 'pbkdf2_sha256': return False
        salt = base64.urlsafe_b64decode(salt64.encode())
        expected = base64.urlsafe_b64decode(dk64.encode())
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def _unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))

def create_token(user: User, ttl_seconds: int = 8 * 3600) -> str:
    secret = os.getenv('JWT_SECRET', 'dev-only-change-me')
    header = {'alg':'HS256','typ':'JWT'}
    payload = {'sub':user.email,'name':user.name,'role':user.role,'exp':int(time.time())+ttl_seconds}
    h = _b64url(json.dumps(header,separators=(',',':')).encode())
    p = _b64url(json.dumps(payload,separators=(',',':')).encode())
    sig = _b64url(hmac.new(secret.encode(), f'{h}.{p}'.encode(), hashlib.sha256).digest())
    return f'{h}.{p}.{sig}'

def decode_token(token: str) -> dict:
    secret = os.getenv('JWT_SECRET', 'dev-only-change-me')
    try:
        h,p,s = token.split('.')
        expected = _b64url(hmac.new(secret.encode(), f'{h}.{p}'.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(s, expected): raise ValueError('signature')
        payload = json.loads(_unb64url(p))
        if int(payload['exp']) < int(time.time()): raise ValueError('expired')
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail='Invalid or expired token')

# Routes a user may call while still holding the shared initial password.
PASSWORD_CHANGE_ROUTES = {'/api/auth/me', '/api/auth/change-password', '/api/auth/profile', '/api/workspaces', '/api/system/info'}

def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail='Authentication required')
    payload = decode_token(credentials.credentials)
    user = db.query(User).filter(User.email == payload['sub']).first()
    if not user: raise HTTPException(status_code=401, detail='User not found')
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_ROUTES:
        raise HTTPException(status_code=403, detail='password_change_required')
    return user
