"""question_logs key by thread and turn

Revision ID: e1f4b7c2a906
Revises: c5e8a1d3f702
Create Date: 2026-10-31 18:00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f4b7c2a906"
down_revision: str | Sequence[str] | None = "c5e8a1d3f702"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE question_logs DROP CONSTRAINT question_logs_pkey")
    # 기존 행은 전부 스레드의 첫 질문이다.
    op.execute("ALTER TABLE question_logs ADD COLUMN turn integer NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE question_logs ALTER COLUMN turn DROP DEFAULT")
    op.execute("ALTER TABLE question_logs ADD PRIMARY KEY (thread_id, turn)")


def downgrade() -> None:
    """Downgrade schema."""
    # 키가 thread_id로 돌아가면 둘째 턴부터는 담을 수 없다.
    op.execute("DELETE FROM question_logs WHERE turn > 1")
    op.execute("ALTER TABLE question_logs DROP CONSTRAINT question_logs_pkey")
    op.execute("ALTER TABLE question_logs DROP COLUMN turn")
    op.execute("ALTER TABLE question_logs ADD PRIMARY KEY (thread_id)")
