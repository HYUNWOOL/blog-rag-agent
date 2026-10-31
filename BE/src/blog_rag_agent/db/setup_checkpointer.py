"""체크포인터 테이블을 만든다. 여러 번 돌려도 안전하다.

실행: uv run python -m blog_rag_agent.db.setup_checkpointer

Alembic 규칙의 예외다(notes/decisions.md). setup()은 라이브러리가 자기 테이블을 직접 관리하고,
CREATE INDEX CONCURRENTLY가 있어 Alembic 트랜잭션 안에서 돌릴 수 없다.
"""

from langgraph.checkpoint.postgres import PostgresSaver

from blog_rag_agent.config import load_settings


def main() -> None:
    with PostgresSaver.from_conn_string(load_settings().database_url) as checkpointer:
        checkpointer.setup()
    print("checkpoint tables ready")


if __name__ == "__main__":
    main()
