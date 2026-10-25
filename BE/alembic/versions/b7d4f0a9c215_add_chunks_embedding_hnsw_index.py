"""add chunks embedding hnsw index

Revision ID: b7d4f0a9c215
Revises: a3c1e7d2b904
Create Date: 2026-10-25 10:05:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d4f0a9c215"
down_revision: str | Sequence[str] | None = "a3c1e7d2b904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # vector_cosine_ops는 <=>(코사인 거리) 연산자와 짝이다. search도 <=>로 정렬해야 이 인덱스를 탄다.
    op.execute(
        "CREATE INDEX chunks_embedding_hnsw ON chunks"
        " USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX chunks_embedding_hnsw")
