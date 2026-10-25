"""data/posts/*.md를 posts·chunks 테이블에 적재한다. 몇 번 돌려도 결과가 같다.

실행: uv run python -m blog_rag_agent.ingest.load
"""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from blog_rag_agent.config import load_settings
from blog_rag_agent.ingest.chunking import chunk_post
from blog_rag_agent.ingest.collect import POSTS_DIR

UPSERT_POST = """
INSERT INTO posts (url, title, published_at, updated_at, tags, content_hash, body)
VALUES (%(url)s, %(title)s, %(published_at)s, %(updated_at)s, %(tags)s, %(content_hash)s, %(body)s)
ON CONFLICT (url) DO UPDATE SET
    title = EXCLUDED.title,
    published_at = EXCLUDED.published_at,
    updated_at = EXCLUDED.updated_at,
    tags = EXCLUDED.tags,
    content_hash = EXCLUDED.content_hash,
    body = EXCLUDED.body
RETURNING id
"""


@dataclass(frozen=True)
class PostFile:
    url: str
    title: str
    published_at: datetime
    updated_at: datetime
    tags: list[str]
    content_hash: str
    body: str


def parse_post_file(path: Path) -> PostFile:
    # collect.render_file이 쓴 형식: "---\n키: JSON값\n...\n---\n\n본문"
    _, head, body = path.read_text(encoding="utf-8").split("---\n", 2)
    meta = {
        k: json.loads(v) for k, v in (line.split(": ", 1) for line in head.splitlines())
    }
    body = body.removeprefix("\n")
    return PostFile(
        url=meta["url"],
        title=meta["title"],
        published_at=datetime.fromisoformat(meta["published_at"]),
        updated_at=datetime.fromisoformat(meta["updated_at"]),
        tags=meta["tags"],
        # 파일의 content_hash를 믿지 않고 읽은 본문으로 다시 계산한다. 손으로 고친 파일도 감지된다.
        content_hash="sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
        body=body,
    )


def load_post(conn: psycopg.Connection, post: PostFile, embedder) -> str:
    """글 하나를 적재한다. 반환값: "unchanged" 또는 "embedded"."""
    # autocommit이어야 conn.transaction()이 진짜 BEGIN/COMMIT이 된다(아니면 세이브포인트라 커밋이 안 된다).
    assert conn.autocommit, "load_post에는 autocommit 연결을 넘긴다"
    row = conn.execute(
        "SELECT content_hash FROM posts WHERE url = %s", (post.url,)
    ).fetchone()
    if row and row[0] == post.content_hash:
        # 본문이 같으면 메타데이터(제목·태그 등)만 갱신하고 임베딩은 건너뛴다.
        with conn.transaction():
            conn.execute(UPSERT_POST, vars(post))
        return "unchanged"

    chunks = chunk_post(post.title, post.body)
    # 느린 임베딩은 트랜잭션 밖에서 한다. 실패해도 DB에는 아무것도 바뀌지 않는다.
    vectors = embedder.embed([c.text for c in chunks])

    # 트랜잭션 경계: posts upsert + 기존 chunks 삭제 + 새 chunks 삽입이 한 번에 커밋되거나 한 번에 취소된다.
    with conn.transaction():
        post_id = conn.execute(UPSERT_POST, vars(post)).fetchone()[0]
        conn.execute("DELETE FROM chunks WHERE post_id = %s", (post_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (post_id, chunk_index, heading, text, embedding)"
                " VALUES (%s, %s, %s, %s, %s)",
                [
                    (post_id, i, c.heading, c.text, np.asarray(v, dtype=np.float32))
                    for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
                ],
            )
    return "embedded"


def load_dir(
    conn: psycopg.Connection, posts_dir: Path, embedder
) -> tuple[Counter, list[str]]:
    counts: Counter = Counter()
    failed: list[str] = []
    for path in sorted(posts_dir.glob("*.md")):
        try:
            counts[load_post(conn, parse_post_file(path), embedder)] += 1
        except (psycopg.Error, ValueError, KeyError, OSError) as e:
            # 한 글이 실패해도 그 글의 트랜잭션만 취소되고 나머지는 계속 적재한다.
            failed.append(f"{path.name}\t{type(e).__name__}: {e}")
    return counts, failed


def main() -> None:
    from blog_rag_agent.embedding import LocalEmbedder

    settings = load_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        # numpy 배열을 vector 타입으로 보내려면 연결마다 등록해야 한다.
        register_vector(conn)
        counts, failed = load_dir(
            conn, POSTS_DIR, LocalEmbedder(settings.embedding_model)
        )
        posts, chunks = conn.execute(
            "SELECT (SELECT count(*) FROM posts), (SELECT count(*) FROM chunks)"
        ).fetchone()
    print(f"{dict(counts)} failed={len(failed)} | posts={posts} chunks={chunks}")
    for line in failed:
        print(f"FAILED {line}")


if __name__ == "__main__":
    main()
