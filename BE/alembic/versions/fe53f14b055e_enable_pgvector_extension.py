"""enable pgvector extension

Revision ID: fe53f14b055e
Revises:
Create Date: 2026-10-19 16:16:40.750048

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fe53f14b055e"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # vector 타입을 쓰는 테이블보다 먼저 있어야 한다. IF NOT EXISTS라 다시 돌려도 안전하다.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP EXTENSION IF EXISTS vector")
