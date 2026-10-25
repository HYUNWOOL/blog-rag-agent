import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from alembic.config import Config
from dotenv import dotenv_values
from pgvector.psycopg import register_vector
from psycopg import sql

from alembic import command
from blog_rag_agent.config import DEFAULT_ENV_FILE

BE_DIR = Path(__file__).resolve().parents[1]
TEST_DB = "rag_test"


def _database_url() -> str:
    # DATABASE_URL만 읽는다. load_dotenv를 쓰면 API 키까지 환경에 올라가 다른 테스트에 섞인다.
    return (
        os.environ.get("DATABASE_URL")
        or dotenv_values(DEFAULT_ENV_FILE)["DATABASE_URL"]
    )


def _with_db_name(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """rag_test DB를 만들고(없을 때만) alembic upgrade head를 적용한다. 세션당 한 번."""
    main_url = _database_url()
    url = _with_db_name(main_url, TEST_DB)

    # CREATE DATABASE는 트랜잭션 안에서 못 돌리므로 autocommit 연결을 쓴다.
    with psycopg.connect(main_url, autocommit=True) as admin:
        exists = admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)
        ).fetchone()
        if not exists:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))

    # alembic/env.py는 환경변수 DATABASE_URL을 .env보다 우선한다. 마이그레이션 동안만 테스트 DB로 바꾼다.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(Config(str(BE_DIR / "alembic.ini")), "head")
    finally:
        if previous is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = previous
    return url


@pytest.fixture
def db(test_db_url):
    """테스트마다 public 테이블을 비운 rag_test 연결. alembic_version은 남긴다."""
    # 적재 코드와 같은 autocommit 연결. conn.transaction()이 진짜 트랜잭션이 된다.
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        # 실수로 개발 DB를 비우지 않도록 대상 DB 이름을 확인한다.
        assert conn.info.dbname == TEST_DB
        register_vector(conn)
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables"
                " WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ]
        if tables:
            conn.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(map(sql.Identifier, tables))
                )
            )
        yield conn
