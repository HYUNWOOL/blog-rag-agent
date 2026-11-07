"""접근 코드 발급. 원문 코드는 이 출력에서 한 번만 보이고 DB에는 해시만 남는다.

uv run python -m blog_rag_agent.api.issue_code "회사 이름" [--days 30] [--limit 20]
"""

import argparse
import secrets
from datetime import UTC, datetime, timedelta

import psycopg

from blog_rag_agent.api.security import hash_code
from blog_rag_agent.api.settings import load_api_settings

INSERT = """
INSERT INTO access_codes (code_hash, company, expires_at, daily_question_limit)
VALUES (%s, %s, %s, %s) RETURNING id
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("company")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, help="하루 질문 한도. 없으면 DAILY_QUESTION_LIMIT")
    args = parser.parse_args()
    settings = load_api_settings()
    code = secrets.token_urlsafe(16)
    expires_at = datetime.now(UTC) + timedelta(days=args.days)
    limit = args.limit or settings.daily_question_limit
    with psycopg.connect(settings.database_url) as conn:
        (code_id,) = conn.execute(
            INSERT,
            (hash_code(settings.access_code_pepper, code), args.company, expires_at, limit),
        ).fetchone()
    print(f"id {code_id}, {args.company}, 만료 {expires_at:%Y-%m-%d %H:%M} UTC, 하루 {limit}회")
    print(f"접근 코드(다시 볼 수 없음): {code}")


if __name__ == "__main__":
    main()
