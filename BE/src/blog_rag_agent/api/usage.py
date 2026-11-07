"""access_codes·usage_log SQL. 연결 풀은 dict_row, autocommit이다."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from psycopg import AsyncConnection

FIND_CODE = """
SELECT id, code_hash, expires_at FROM access_codes WHERE code_hash = %s
"""
LOCK_CODE = """
SELECT expires_at, daily_question_limit FROM access_codes WHERE id = %s FOR UPDATE
"""
# 한국 시간 자정부터 지금까지. 실패한 요청도 비용이 들었을 수 있어 같이 센다.
COUNT_TODAY = """
SELECT count(*) AS n FROM usage_log
WHERE code_id = %s
  AND created_at >= date_trunc('day', now() AT TIME ZONE 'Asia/Seoul') AT TIME ZONE 'Asia/Seoul'
"""
RESERVE = """
INSERT INTO usage_log (code_id, thread_id) VALUES (%s, %s) RETURNING id
"""
FINISH = """
UPDATE usage_log
SET status = %(status)s, turn = %(turn)s, input_tokens = %(input_tokens)s,
    output_tokens = %(output_tokens)s, cost_usd = %(cost_usd)s, finished_at = now()
WHERE id = %(id)s
"""
SOURCES = """
SELECT id, title, url FROM posts WHERE id = ANY(%s)
"""


@dataclass(frozen=True)
class Reservation:
    """reserve의 결과. usage_id가 None이면 거절이고 reason이 이유다."""

    usage_id: int | None
    reason: str | None = None  # "invalid" | "limit"


async def find_code(conn: AsyncConnection, code_hash: bytes) -> dict | None:
    cur = await conn.execute(FIND_CODE, (code_hash,))
    return await cur.fetchone()


async def reserve(
    conn: AsyncConnection, code_id: int, thread_id: str, now: datetime
) -> Reservation:
    """한도 안이면 started 행을 넣어 한 번을 예약한다. 같은 코드의 동시 요청은 행 잠금으로 줄을 세운다."""
    async with conn.transaction():
        cur = await conn.execute(LOCK_CODE, (code_id,))
        code = await cur.fetchone()
        if code is None or code["expires_at"] <= now:
            return Reservation(None, "invalid")
        used = (await (await conn.execute(COUNT_TODAY, (code_id,))).fetchone())["n"]
        if used >= code["daily_question_limit"]:
            return Reservation(None, "limit")
        row = await (await conn.execute(RESERVE, (code_id, thread_id))).fetchone()
        return Reservation(row["id"])


async def finish(
    conn: AsyncConnection,
    usage_id: int,
    *,
    status: str,
    turn: int | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
) -> None:
    await conn.execute(
        FINISH,
        {
            "id": usage_id,
            "status": status,
            "turn": turn,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        },
    )


async def sources(conn: AsyncConnection, post_ids: list[int]) -> list[dict]:
    rows = {r["id"]: r for r in await (await conn.execute(SOURCES, (post_ids,))).fetchall()}
    # 그래프가 정한 근거 순서를 지킨다.
    return [
        {"title": rows[p]["title"], "url": rows[p]["url"]} for p in post_ids if p in rows
    ]
