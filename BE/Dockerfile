# 웹 서버 이미지. Railway 서비스의 Root Directory를 /BE로 두면 이 파일을 자동으로 쓴다.
# 로컬 확인: docker build -t blog-rag-agent . && docker run --env-file .env -e PORT=8000 -p 8000:8000 blog-rag-agent
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    HF_HOME=/opt/hf \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /opt/hf && chown app /opt/hf

WORKDIR /app

# 의존성만 먼저 설치해 소스가 바뀌어도 이 층(수백 MB)과 모델 층을 다시 만들지 않는다.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# bge-m3 가중치(약 2.3GB)를 이미지에 굽는다(결정: notes/decisions.md 3주차 Railway).
# 실행 사용자(app)로 받아 두어야 실행 중 캐시 잠금 파일을 만들 수 있다.
# 로딩 중 transformers가 같은 가중치를 safetensors로 바꾼 PR 리비전(약 2.2GB)을 하나 더 받으므로,
# main이 아닌 리비전은 같은 층에서 지운다. 그다음 오프라인으로 한 번 임베딩해 실행 때 쓸 수 있는지 확인한다.
USER app
RUN /opt/venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')" \
    && /opt/venv/bin/python -c "from huggingface_hub import scan_cache_dir; info = scan_cache_dir(); info.delete_revisions(*[r.commit_hash for repo in info.repos for r in repo.revisions if 'main' not in r.refs]).execute()" \
    && HF_HUB_OFFLINE=1 /opt/venv/bin/python -c "from sentence_transformers import SentenceTransformer; assert SentenceTransformer('BAAI/bge-m3').encode(['확인']).shape == (1, 1024)" \
    && du -sh /opt/hf
USER root

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY static ./static
# 프로젝트는 편집 가능 설치로 /app/src를 가리킨다. app.py는 /app/static을 이 경로 기준으로 찾는다.
RUN uv sync --locked --no-dev

# 실행 중에는 Hugging Face에 접속하지 않고 구워 둔 가중치만 쓴다.
ENV PATH=/opt/venv/bin:$PATH \
    HF_HUB_OFFLINE=1

USER app
EXPOSE 8000

# 비공개 네트워크(DB)는 빌드 때 닿지 않으므로 마이그레이션은 시작할 때 한다. 둘 다 여러 번 돌려도 안전하다.
CMD ["sh", "-c", "alembic upgrade head && python -m blog_rag_agent.db.setup_checkpointer && exec python -m blog_rag_agent.api --host 0.0.0.0 --port ${PORT:-8000}"]
