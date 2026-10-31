"""질문 로그. 재시도나 재개로 노드가 다시 돌아도 (thread_id, turn)당 한 행만 남는다."""

import psycopg

UPSERT_LOG = """
INSERT INTO question_logs
    (thread_id, turn, question, status, answer, attempts, llm_calls, source_post_ids)
VALUES
    (%(thread_id)s, %(turn)s, %(question)s, %(status)s, %(answer)s, %(attempts)s,
     %(llm_calls)s, %(source_post_ids)s)
ON CONFLICT (thread_id, turn) DO UPDATE SET
    status = EXCLUDED.status,
    answer = EXCLUDED.answer,
    attempts = EXCLUDED.attempts,
    llm_calls = EXCLUDED.llm_calls,
    source_post_ids = EXCLUDED.source_post_ids,
    updated_at = now()
"""


def upsert_question_log(conn: psycopg.Connection, **row) -> None:
    conn.execute(UPSERT_LOG, row)
