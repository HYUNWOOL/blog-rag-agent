"""접근 코드 해시와 서명 세션 쿠키. 표준 라이브러리 hmac만 쓴다."""

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass

SESSION_COOKIE = "session"
SESSION_SECONDS = 2 * 60 * 60
# 코드가 DB에 없을 때도 같은 비교를 한 번 해서 응답 시간 차이를 줄인다.
DUMMY_HASH = bytes(32)


def hash_code(pepper: bytes, code: str) -> bytes:
    return hmac.new(pepper, code.strip().encode(), hashlib.sha256).digest()


def hashes_match(stored: bytes | None, candidate: bytes) -> bool:
    return hmac.compare_digest(stored or DUMMY_HASH, candidate) and stored is not None


@dataclass(frozen=True)
class Session:
    code_id: int
    thread_id: str
    expires_at: int


def _sign(secret: bytes, payload: str) -> str:
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def new_session(secret: bytes, code_id: int, now: float | None = None) -> tuple[Session, str]:
    """세션마다 thread_id를 새로 묶는다. 쿠키 값은 code_id:thread_id:만료:서명."""
    expires_at = int(now if now is not None else time.time()) + SESSION_SECONDS
    session = Session(code_id, str(uuid.uuid4()), expires_at)
    payload = f"{session.code_id}:{session.thread_id}:{session.expires_at}"
    return session, f"{payload}:{_sign(secret, payload)}"


def read_session(secret: bytes, cookie: str | None, now: float | None = None) -> Session | None:
    if not cookie:
        return None
    payload, _, signature = cookie.rpartition(":")
    if not hmac.compare_digest(_sign(secret, payload), signature):
        return None
    try:
        code_id, thread_id, expires_at = payload.split(":")
        session = Session(int(code_id), thread_id, int(expires_at))
    except ValueError:
        return None
    if session.expires_at <= (now if now is not None else time.time()):
        return None
    return session
