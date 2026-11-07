"""create access_codes and usage_log

Revision ID: f2a6c9d1e803
Revises: e1f4b7c2a906
Create Date: 2026-11-07 12:00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a6c9d1e803"
down_revision: str | Sequence[str] | None = "e1f4b7c2a906"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE access_codes (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            -- HMAC-SHA256(ACCESS_CODE_PEPPER, 코드). 원문 코드는 저장하지 않는다.
            code_hash bytea NOT NULL UNIQUE CHECK (octet_length(code_hash) = 32),
            company text NOT NULL,
            expires_at timestamptz NOT NULL,
            daily_question_limit integer NOT NULL CHECK (daily_question_limit > 0),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE usage_log (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            code_id bigint NOT NULL REFERENCES access_codes (id) ON DELETE CASCADE,
            -- 요청 시작 시각. 하루 한도는 이 값의 Asia/Seoul 날짜로 센다.
            created_at timestamptz NOT NULL DEFAULT now(),
            thread_id text NOT NULL,
            -- 시작 때는 아직 턴을 모른다. 그래프가 끝나면 채운다.
            turn integer,
            -- started: 한도에서 한 번을 예약함. 실패도 비용이 들었을 수 있어 한도에 센다.
            status text NOT NULL DEFAULT 'started'
                CHECK (status IN ('started', 'done', 'failed')),
            input_tokens integer NOT NULL DEFAULT 0,
            output_tokens integer NOT NULL DEFAULT 0,
            cost_usd numeric(12, 6) NOT NULL DEFAULT 0,
            finished_at timestamptz
        )
        """
    )
    op.execute("CREATE INDEX usage_log_code_created ON usage_log (code_id, created_at)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE usage_log")
    op.execute("DROP TABLE access_codes")
