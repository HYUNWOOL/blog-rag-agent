"""웹 서버: 접근 코드 세션, 하루 한도, 그래프 답변 SSE 스트리밍, 사용량 기록.

실행: uv run python -m blog_rag_agent.api
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.sse import format_sse_event
from fastapi.staticfiles import StaticFiles
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from blog_rag_agent.api import usage
from blog_rag_agent.api.security import (
    SESSION_COOKIE,
    SESSION_SECONDS,
    hash_code,
    hashes_match,
    new_session,
    read_session,
)
from blog_rag_agent.api.settings import ApiSettings, cost_usd
from blog_rag_agent.api.stream import AnswerExtractor
from blog_rag_agent.graph.agentic import run_config

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parents[3] / "static"  # BE/static
MAX_QUESTION_CHARS = 1000

# (settings, checkpointer) -> 그래프를 여는 컨텍스트 매니저. 테스트는 가짜 그래프를 넣는다.
GraphFactory = Callable[[ApiSettings, AsyncPostgresSaver], AbstractAsyncContextManager]


@asynccontextmanager
async def open_real_graph(settings: ApiSettings, checkpointer: AsyncPostgresSaver):
    from langchain_anthropic import ChatAnthropic
    from pgvector.psycopg import register_vector

    from blog_rag_agent.embedding import LocalEmbedder
    from blog_rag_agent.graph.agentic import build_graph

    embedder = LocalEmbedder(settings.embedding_model)
    model = ChatAnthropic(
        model=settings.chat_model,
        api_key=settings.anthropic_api_key,
        max_tokens=settings.answer_max_tokens,
        effort="low",
    )
    # 그래프의 검색·질문 로그는 동기 연결 하나를 쓴다(노드가 asyncio.to_thread로 부른다).
    # shortcut: 동시 요청이 이 연결 하나를 나눠 쓴다(psycopg가 잠금으로 줄을 세움). 동시 사용자가 늘면 풀로 바꾼다.
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        register_vector(conn)
        yield build_graph(conn, embedder, model, checkpointer)


class SessionRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


def sse(event: str, data) -> bytes:
    return format_sse_event(event=event, data_str=json.dumps(data, ensure_ascii=False))


def create_app(settings: ApiSettings, graph_factory: GraphFactory = open_real_graph) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 체크포인터가 요구하는 연결 옵션(autocommit, prepare_threshold=0, dict_row)을 풀 전체에 건다.
        pool = AsyncConnectionPool(
            settings.database_url,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        async with pool:
            checkpointer = AsyncPostgresSaver(pool)
            async with graph_factory(settings, checkpointer) as graph:
                app.state.pool = pool
                app.state.graph = graph
                yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    async def healthz(request: Request):
        try:
            async with request.app.state.pool.connection(timeout=3) as conn:
                await conn.execute("SELECT 1")
        except Exception:
            log.exception("healthz: DB 연결 실패")
            return JSONResponse({"status": "db_unavailable"}, status_code=503)
        return {"status": "ok"}

    @app.post("/api/session", status_code=204)
    async def create_session(body: SessionRequest, request: Request, response: Response):
        candidate = hash_code(settings.access_code_pepper, body.code)
        async with request.app.state.pool.connection() as conn:
            row = await usage.find_code(conn, candidate)
        stored = bytes(row["code_hash"]) if row else None
        if not hashes_match(stored, candidate) or row["expires_at"] <= datetime.now(UTC):
            # 없는 코드와 만료된 코드를 같은 응답으로 돌려, 코드가 있었는지 알려 주지 않는다.
            raise HTTPException(401, "접근 코드가 맞지 않거나 만료됐습니다")
        _, cookie = new_session(settings.session_secret, row["id"])
        response.set_cookie(
            SESSION_COOKIE,
            cookie,
            max_age=SESSION_SECONDS,
            httponly=True,
            secure=True,
            samesite="lax",
        )

    @app.post("/api/chat")
    async def chat(body: ChatRequest, request: Request):
        session = read_session(settings.session_secret, request.cookies.get(SESSION_COOKIE))
        if session is None:
            raise HTTPException(401, "세션이 없거나 만료됐습니다")
        pool = request.app.state.pool
        async with pool.connection() as conn:
            reservation = await usage.reserve(
                conn, session.code_id, session.thread_id, datetime.now(UTC)
            )
        if reservation.reason == "invalid":
            raise HTTPException(401, "접근 코드가 만료됐습니다")
        if reservation.reason == "limit":
            raise HTTPException(429, "오늘 질문 한도를 다 썼습니다")
        events = answer_events(
            request.app.state.graph, pool, settings, session.thread_id,
            reservation.usage_id, body.question,
        )
        return StreamingResponse(events, media_type="text/event-stream")

    # API 경로 뒤에 마운트해야 /api/*가 정적 파일에 가리지 않는다.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


async def answer_events(
    graph, pool, settings: ApiSettings, thread_id: str, usage_id: int, question: str
) -> AsyncIterator[bytes]:
    """token 이벤트로 답 글자를, 마지막 sources 이벤트로 근거 글을 보낸다. 끝나면 usage_log를 채운다."""
    tokens = UsageMetadataCallbackHandler()
    config = {**run_config(thread_id), "callbacks": [tokens]}
    extractor = AnswerExtractor()
    status, turn = "failed", None
    try:
        async for message, meta in graph.astream(
            {"question": question}, config, stream_mode="messages"
        ):
            # grade(판정 JSON)와 rewrite_query(검색어) 토큰은 사용자에게 보내지 않는다.
            # shortcut: answer 노드가 재시도되면 앞 시도의 글자가 이미 나갔을 수 있다. 재시도가 잦아지면 시도별로 끊는다.
            if meta.get("langgraph_node") == "answer" and (piece := extractor.feed(message.text)):
                yield sse("token", {"text": piece})
        state = (await graph.aget_state(config)).values
        if state["status"] == "insufficient":
            # insufficient 노드는 LLM을 부르지 않아 스트림에 토큰이 없다. 안내문을 한 번에 보낸다.
            yield sse("token", {"text": state["answer"]})
        async with pool.connection() as conn:
            yield sse("sources", await usage.sources(conn, state["source_post_ids"]))
        status, turn = "done", state["turn"]
    except Exception:
        log.exception("chat 실패 thread=%s", thread_id)
        yield sse("error", {"message": "답변 중 오류가 났습니다. 잠시 뒤 다시 시도해 주세요."})
    finally:
        totals = list(tokens.usage_metadata.values())
        input_tokens = sum(u.get("input_tokens", 0) for u in totals)
        output_tokens = sum(u.get("output_tokens", 0) for u in totals)

        async def record():
            async with pool.connection() as conn:
                await usage.finish(
                    conn, usage_id, status=status, turn=turn,
                    input_tokens=input_tokens, output_tokens=output_tokens,
                    cost_usd=cost_usd(settings.chat_model, input_tokens, output_tokens),
                )

        # 클라이언트가 끊어 취소돼도 이미 쓴 토큰과 비용은 남긴다.
        await asyncio.shield(record())


def app_from_env() -> FastAPI:
    from blog_rag_agent.api.settings import load_api_settings

    return create_app(load_api_settings())
