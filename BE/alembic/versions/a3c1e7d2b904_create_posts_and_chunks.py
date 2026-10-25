"""create posts and chunks

Revision ID: a3c1e7d2b904
Revises: fe53f14b055e
Create Date: 2026-10-25 10:00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c1e7d2b904"
down_revision: str | Sequence[str] | None = "fe53f14b055e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE posts (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            -- 재적재 때 같은 글을 찾는 키. 수집 파일 이름도 url에서 나온다.
            url text NOT NULL UNIQUE,
            title text NOT NULL,
            published_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            tags text[] NOT NULL DEFAULT '{}',
            -- 본문 마크다운의 sha256. 같으면 청크를 다시 만들거나 임베딩하지 않는다.
            content_hash text NOT NULL,
            -- get_post가 원문 전체를 돌려줄 수 있게 본문도 둔다.
            body text NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chunks (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            post_id bigint NOT NULL REFERENCES posts (id) ON DELETE CASCADE,
            chunk_index integer NOT NULL,
            heading text,
            text text NOT NULL,
            -- BAAI/bge-m3 출력 차원. 모델을 바꾸면 이 타입부터 마이그레이션해야 한다.
            embedding vector(1024) NOT NULL,
            UNIQUE (post_id, chunk_index)
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE chunks")
    op.execute("DROP TABLE posts")
