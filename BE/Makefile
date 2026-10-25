.PHONY: db-up db-reset migrate test

db-up:
	docker compose up -d --wait

# 볼륨(데이터 파일)은 두고, 스키마만 마이그레이션으로 내렸다가 다시 올린다. DDL을 손으로 실행하지 않는다.
db-reset:
	uv run alembic downgrade base
	uv run alembic upgrade head

migrate:
	uv run alembic upgrade head

test:
	uv run pytest
