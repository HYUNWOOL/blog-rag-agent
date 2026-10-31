.PHONY: db-up db-reset migrate checkpoints test

db-up:
	docker compose up -d --wait

# 볼륨(데이터 파일)은 두고, 스키마만 마이그레이션으로 내렸다가 다시 올린다. DDL을 손으로 실행하지 않는다.
db-reset:
	uv run alembic downgrade base
	uv run alembic upgrade head

migrate:
	uv run alembic upgrade head

# 체크포인터 테이블은 라이브러리가 관리한다(Alembic 규칙의 예외, notes/decisions.md).
checkpoints:
	uv run python -m blog_rag_agent.db.setup_checkpointer

test:
	uv run pytest
