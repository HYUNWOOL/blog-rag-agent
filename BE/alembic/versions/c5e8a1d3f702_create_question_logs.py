"""create question_logs

Revision ID: c5e8a1d3f702
Revises: b7d4f0a9c215
Create Date: 2026-10-31 10:00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5e8a1d3f702"
down_revision: str | Sequence[str] | None = "b7d4f0a9c215"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE question_logs (
            -- 멱등키. 스레드 하나에 질문 하나이므로, 노드가 다시 돌아도 같은 행을 덮어쓴다.
            thread_id text PRIMARY KEY,
            question text NOT NULL,
            status text NOT NULL CHECK (status IN ('answered', 'insufficient')),
            answer text NOT NULL,
            attempts integer NOT NULL,
            llm_calls integer NOT NULL,
            source_post_ids bigint[] NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE question_logs")
