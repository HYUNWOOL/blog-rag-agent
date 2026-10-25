"""questions.txt의 질문마다 search 결과 상위 k개를 마크다운 표로 찍는다.

질문 파일: 한 줄에 질문 하나, 빈 줄과 #으로 시작하는 줄은 건너뛴다.
실행: uv run python experiments/week1/search_questions.py [k]
"""

import sys
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from blog_rag_agent.config import load_settings
from blog_rag_agent.embedding import LocalEmbedder
from blog_rag_agent.retrieval.search import search

QUESTIONS = Path(__file__).with_name("questions.txt")


def main() -> None:
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    if not QUESTIONS.exists():
        sys.exit(f"{QUESTIONS} 가 없습니다. 질문을 한 줄에 하나씩 적어 주세요.")
    lines = QUESTIONS.read_text(encoding="utf-8").splitlines()
    questions = [q.strip() for q in lines if q.strip() and not q.startswith("#")]

    settings = load_settings()
    embedder = LocalEmbedder(settings.embedding_model)
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        register_vector(conn)
        print("| # | 질문 | 순위 | 거리 | 글 > 소제목 |")
        print("| --- | --- | --- | --- | --- |")
        for i, q in enumerate(questions, 1):
            for rank, hit in enumerate(search(conn, embedder, q, k), 1):
                where = f"{hit['title']} > {hit['heading'] or '(도입)'}"
                label = q if rank == 1 else ""
                print(f"| {i} | {label} | {rank} | {hit['distance']:.3f} | {where} |")


if __name__ == "__main__":
    main()
