"""Sign-in throttles shared by every API process and replica (stored in the database, not in process memory)."""
from __future__ import annotations

import time

from .db import SessionLocal
from .models import AuthThrottleEvent

# Rows older than this are never needed by any window; they are deleted as new events arrive.
_KEEP_SECONDS = 24 * 3600


def hits(key: str, window_seconds: float) -> int:
    db = SessionLocal()
    try:
        return db.query(AuthThrottleEvent).filter(AuthThrottleEvent.key == key, AuthThrottleEvent.at >= time.time() - window_seconds).count()
    finally:
        db.close()


def record(key: str) -> None:
    db = SessionLocal()
    try:
        now = time.time()
        db.add(AuthThrottleEvent(key=key[:255], at=now))
        db.query(AuthThrottleEvent).filter(AuthThrottleEvent.at < now - _KEEP_SECONDS).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def clear(key: str | None = None) -> None:
    """Forget one key (after a successful sign-in), or everything (tests)."""
    db = SessionLocal()
    try:
        query = db.query(AuthThrottleEvent)
        if key is not None:
            query = query.filter(AuthThrottleEvent.key == key[:255])
        query.delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def check_and_record(key: str, limit: int, window_seconds: float) -> bool:
    """Record one request for ``key``; True when the window already holds ``limit`` requests (then nothing is recorded)."""
    if hits(key, window_seconds) >= limit:
        return True
    record(key)
    return False
