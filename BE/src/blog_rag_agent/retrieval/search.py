"""chunks 벡터 검색과 글 조회. psycopg로 SQL을 직접 쓴다."""

import numpy as np
import psycopg
from psycopg.rows import dict_row

# ORDER BY의 <=>가 HNSW 인덱스의 vector_cosine_ops와 짝이라 인덱스를 탈 수 있다.
# top-k를 chunks에서 먼저 뽑고 나서 JOIN한다. JOIN 뒤에 ORDER BY ... LIMIT를 두면
# 플래너가 HNSW 정렬 스캔을 쓸 수 없어 데이터가 커져도 전체 스캔 + 정렬이 된다(EXPLAIN으로 확인).
SEARCH_SQL = """
WITH top AS (
    SELECT id, post_id, heading, text, embedding <=> %(q)s AS distance
    FROM chunks
    ORDER BY embedding <=> %(q)s
    LIMIT %(k)s
)
SELECT top.id AS chunk_id, top.post_id, p.title, p.url, top.heading, top.text,
       top.distance
FROM top
JOIN posts p ON p.id = top.post_id
ORDER BY top.distance
"""


def search(conn: psycopg.Connection, embedder, query: str, k: int = 5) -> list[dict]:
    """질문과 코사인 거리가 가까운 청크 k개. distance는 0(같음)~2(반대)."""
    vector = np.asarray(embedder.embed([query])[0], dtype=np.float32)
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(SEARCH_SQL, {"q": vector, "k": k}).fetchall()


def get_post(conn: psycopg.Connection, post_id: int) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            "SELECT id, url, title, published_at, updated_at, tags, body"
            " FROM posts WHERE id = %s",
            (post_id,),
        ).fetchone()
