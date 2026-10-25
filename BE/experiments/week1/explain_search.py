"""search SQL의 EXPLAIN ANALYZE를 기본 설정과 enable_seqscan=off로 찍는다(README 근거).

실행: uv run python experiments/week1/explain_search.py "질문"
"""

import re
import sys

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from blog_rag_agent.config import load_settings
from blog_rag_agent.embedding import LocalEmbedder
from blog_rag_agent.retrieval.search import SEARCH_SQL


def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else "스위스에서 기차 탄 이야기"
    settings = load_settings()
    embedder = LocalEmbedder(settings.embedding_model)
    vector = np.asarray(embedder.embed([question])[0], dtype=np.float32)
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        register_vector(conn)
        rows = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        print(f"질문: {question} / chunks {rows}행")
        for label, setup in [
            ("기본 설정", None),
            ("enable_seqscan = off", "SET LOCAL enable_seqscan = off"),
        ]:
            # SET LOCAL은 이 트랜잭션 안에서만 적용된다. 다른 쿼리에 영향을 남기지 않는다.
            with conn.transaction():
                if setup:
                    conn.execute(setup)
                plan = conn.execute(
                    "EXPLAIN ANALYZE " + SEARCH_SQL, {"q": vector, "k": 5}
                )
                # 1024차원 벡터 리터럴이 계획을 덮으므로 <q>로 줄인다.
                lines = [re.sub(r"'\[[^']*\]'::vector", "<q>", r[0]) for r in plan]
            print(f"\n=== {label}\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
