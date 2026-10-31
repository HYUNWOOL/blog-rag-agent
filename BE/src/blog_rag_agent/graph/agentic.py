"""Agentic RAG 그래프: 검색 → 충분성 판정 → 답변, 부족하면 검색어를 바꿔 재검색.

실행: uv run python -m blog_rag_agent.graph.agentic "질문" [이어 갈 thread_id]
"""

import asyncio
import operator
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import anthropic
import psycopg
from langchain.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.config import get_config
from langgraph.errors import NodeError, NodeTimeoutError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Overwrite, RetryPolicy, TimeoutPolicy
from pgvector.psycopg import register_vector
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from blog_rag_agent.agent_tools import SEARCH_K, SYSTEM_PROMPT, format_context
from blog_rag_agent.config import load_settings
from blog_rag_agent.db.question_log import upsert_question_log
from blog_rag_agent.graph.research import make_model
from blog_rag_agent.graph.trace import traced
from blog_rag_agent.retrieval.search import search

MAX_RETRIES = 2  # 재검색 상한. 총 검색은 3번까지(1주차 멀티홉 질문은 2번이면 충분했다).
# 재검색을 다 쓰면 super-step이 11개(후속 턴은 12개)다. 여유를 두고 넘으면 실패로 멈춘다.
RECURSION_LIMIT = 15
MAX_HISTORY_TURNS = 3  # 프롬프트에 넣는 이전 대화. 턴이 쌓여도 토큰이 늘지 않게 자른다.
LLM_TIMEOUT_SECONDS = 60
RETRIEVE_TIMEOUT_SECONDS = 30

GRADE_PROMPT = (
    "너는 블로그 검색 결과가 질문에 답하기에 충분한지 판정한다. "
    "검색 결과로 질문의 핵심에 답할 수 있으면 세부가 일부 빠져도 sufficient를 true로 한다. "
    "핵심에 답할 내용이 없으면 false로 하고, 부족한 정보를 missing에 한 문장으로 적는다."
)
REWRITE_PROMPT = (
    "너는 블로그 검색어를 만든다. 이 블로그에는 전체 일정을 모은 글이 없고 장소나 구간별 글만 있다. "
    "부족한 정보 중 아직 찾지 못한 구체적인 장소나 구간 하나만 골라 짧은 검색어를 만든다. "
    "이전 검색어와 다르게 쓰고, 검색어만 출력한다."
)
FOLLOWUP_PROMPT = (
    "너는 블로그 검색어를 만든다. 이전 대화를 참고해 마지막 질문을 "
    "대화 없이도 이해되는 짧은 검색어로 바꾼다. 검색어만 출력한다."
)
ANSWER_PROMPT = f"{SYSTEM_PROMPT} source_post_ids에는 답에 실제로 쓴 글의 id만 넣는다."


class Verdict(BaseModel):
    sufficient: bool = Field(description="검색 결과로 질문의 핵심에 답할 수 있는가")
    missing: str = Field(default="", description="부족한 정보. 충분하면 빈 문자열")


class Answer(BaseModel):
    answer: str = Field(description="사용자에게 보여 줄 답변")
    source_post_ids: list[int] = Field(description="답에 실제로 쓴 글의 id")


def merge_chunks(left: list[dict], right: list[dict]) -> list[dict]:
    # 멀티홉 질문은 검색마다 찾은 내용을 모아야 답할 수 있어서 덮어쓰지 않고 합친다.
    seen = {c["chunk_id"] for c in left}
    return left + [c for c in right if c["chunk_id"] not in seen]


class State(TypedDict, total=False):
    question: str
    turn: int
    history: Annotated[list[dict], operator.add]
    query: str
    chunks: Annotated[list[dict], merge_chunks]
    attempts: int
    verdict: dict
    answer: str
    status: str
    source_post_ids: list[int]
    llm_calls: int


def is_transient(exc: Exception) -> bool:
    # LangChain 모델 예외는 재시도 가능 여부를 스스로 알려 준다(인증 오류는 False).
    retryable = getattr(exc, "is_retryable", None)
    if retryable is not None:
        return retryable
    return isinstance(
        exc,
        (
            NodeTimeoutError,  # 내장 TimeoutError의 하위 클래스가 아니다
            TimeoutError,
            ConnectionError,
            anthropic.APIConnectionError,
            psycopg.OperationalError,
        ),
    )


def route_after_begin(state: State) -> Literal["retrieve", "rewrite_query"]:
    return "rewrite_query" if state.get("history") else "retrieve"


def route_after_grade(
    state: State,
) -> Literal["answer", "rewrite_query", "insufficient"]:
    if state["verdict"]["sufficient"]:
        return "answer"
    return "insufficient" if state["attempts"] >= MAX_RETRIES else "rewrite_query"


def with_history(state: State, text: str) -> str:
    turns = state.get("history", [])[-MAX_HISTORY_TURNS:]
    if not turns:
        return text
    lines = "\n".join(f"질문: {t['question']}\n답: {t['answer']}" for t in turns)
    return f"이전 대화:\n{lines}\n\n{text}"


def on_retrieve_failure(state: State, error: NodeError) -> Command:
    # 재시도를 다 쓴 장애만 안내로 돌린다. 코드 버그는 숨기지 않고 그대로 올린다.
    if not is_transient(error.error):
        raise error.error
    missing = "검색 오류로 글을 찾지 못했습니다."
    return Command(
        update={"verdict": {"sufficient": False, "missing": missing}},
        goto="insufficient",
    )


def build_graph(conn, embedder, model, checkpointer, trace_path: Path | None = None):
    grader = model.with_structured_output(Verdict, method="json_schema")
    answerer = model.with_structured_output(Answer, method="json_schema")
    wrap = traced(trace_path) if trace_path else lambda fn: fn

    async def begin_turn(state: State) -> State:
        # 체크포인트에 지난 턴 값이 남아 있으므로 턴마다 비운다. chunks는 reducer를 건너뛴다.
        return {
            "turn": state.get("turn", 0) + 1,
            "query": "",
            "chunks": Overwrite([]),
            "attempts": 0,
            "verdict": {},
            "answer": "",
            "status": "",
            "source_post_ids": [],
            "llm_calls": 0,
        }

    async def retrieve(state: State) -> State:
        query = state["query"] or state["question"]
        # search는 동기 DB·임베딩 호출이라 이벤트 루프를 막지 않게 스레드에서 돌린다.
        hits = await asyncio.to_thread(search, conn, embedder, query, SEARCH_K)
        return {"query": query, "chunks": hits}

    async def grade(state: State) -> State:
        verdict = await grader.ainvoke(
            [
                SystemMessage(GRADE_PROMPT),
                HumanMessage(
                    with_history(
                        state,
                        f"검색 결과:\n\n{format_context(state['chunks'])}\n\n"
                        f"질문: {state['question']}",
                    )
                ),
            ]
        )
        return {"verdict": verdict.model_dump(), "llm_calls": state["llm_calls"] + 1}

    async def rewrite_query(state: State) -> State:
        # query가 비어 있으면 후속 턴의 첫 검색이다. 재검색 횟수에 넣지 않는다.
        retrying = bool(state["query"])
        text = f"질문: {state['question']}"
        if retrying:
            text += (
                f"\n이전 검색어: {state['query']}"
                f"\n부족한 정보: {state['verdict']['missing']}"
            )
        response = await model.ainvoke(
            [
                SystemMessage(REWRITE_PROMPT if retrying else FOLLOWUP_PROMPT),
                HumanMessage(with_history(state, text)),
            ]
        )
        return {
            "query": response.text.strip(),
            "attempts": state["attempts"] + int(retrying),
            "llm_calls": state["llm_calls"] + 1,
        }

    async def answer(state: State) -> State:
        titles = {c["post_id"]: c["title"] for c in state["chunks"]}
        catalog = "\n".join(f"{post_id}: {t}" for post_id, t in titles.items())
        result = await answerer.ainvoke(
            [
                SystemMessage(ANSWER_PROMPT),
                HumanMessage(
                    with_history(
                        state,
                        f"블로그 검색 결과:\n\n{format_context(state['chunks'])}\n\n"
                        f"글 id:\n{catalog}\n\n질문: {state['question']}",
                    )
                ),
            ]
        )
        return {
            "answer": result.answer,
            "status": "answered",
            # 모델이 고른 id는 믿지 않고 이번 턴에 검색된 글만 남긴다.
            "source_post_ids": [
                p for p in dict.fromkeys(result.source_post_ids) if p in titles
            ],
            "llm_calls": state["llm_calls"] + 1,
        }

    async def insufficient(state: State) -> State:
        text = (
            "블로그에서 충분한 내용을 찾지 못했습니다. "
            f"부족한 정보: {state['verdict']['missing']}"
        )
        titles = dict.fromkeys(c["title"] for c in state["chunks"])
        if titles:
            text += f"\n가장 가까운 글: {', '.join(titles)}"
        return {"answer": text, "status": "insufficient"}

    async def log_question(state: State) -> State:
        await asyncio.to_thread(
            upsert_question_log,
            conn,
            thread_id=get_config()["configurable"]["thread_id"],
            turn=state["turn"],
            question=state["question"],
            status=state["status"],
            answer=state["answer"],
            attempts=state["attempts"],
            llm_calls=state["llm_calls"],
            source_post_ids=state["source_post_ids"],
        )
        return {"history": [{"question": state["question"], "answer": state["answer"]}]}

    retry = RetryPolicy(max_attempts=3, retry_on=is_transient)
    llm_timeout = TimeoutPolicy(run_timeout=LLM_TIMEOUT_SECONDS)

    builder = StateGraph(State)
    builder.add_node(wrap(begin_turn))
    builder.add_node(
        wrap(retrieve),
        retry_policy=retry,
        timeout=RETRIEVE_TIMEOUT_SECONDS,
        error_handler=on_retrieve_failure,
    )
    builder.add_node(wrap(grade), retry_policy=retry, timeout=llm_timeout)
    builder.add_node(wrap(rewrite_query), retry_policy=retry, timeout=llm_timeout)
    builder.add_node(wrap(answer), retry_policy=retry, timeout=llm_timeout)
    builder.add_node(wrap(insufficient))
    builder.add_node(wrap(log_question), retry_policy=retry)
    builder.add_edge(START, "begin_turn")
    builder.add_conditional_edges("begin_turn", route_after_begin)
    builder.add_edge("retrieve", "grade")
    builder.add_conditional_edges("grade", route_after_grade)
    builder.add_edge("rewrite_query", "retrieve")
    builder.add_edge("answer", "log_question")
    builder.add_edge("insufficient", "log_question")
    builder.add_edge("log_question", END)
    return builder.compile(checkpointer=checkpointer)


def run_async(coroutine):
    # psycopg 비동기는 Windows 기본 ProactorEventLoop에서 동작하지 않는다.
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def run_config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }


@asynccontextmanager
async def open_graph(trace_path: Path | None = None):
    from blog_rag_agent.embedding import LocalEmbedder

    settings = load_settings()
    embedder = LocalEmbedder(settings.embedding_model)
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as saver:
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            register_vector(conn)
            model = make_model(settings.anthropic_api_key)
            yield build_graph(conn, embedder, model, saver, trace_path)


async def ask(question: str, thread_id: str) -> None:
    config = run_config(thread_id)
    async with open_graph() as graph:
        async for update in graph.astream(
            {"question": question}, config, stream_mode="updates"
        ):
            print(f"[node] {', '.join(update)}")
        state = (await graph.aget_state(config)).values
    print(f"\nthread {thread_id} 턴 {state['turn']}")
    print(f"검색어 {state['query']!r}, LLM {state['llm_calls']}번")
    print(f"근거 글 id: {state['source_post_ids']}")
    print(f"\n{state['answer']}")


def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else "튀르키예 이동 순서 알려줘"
    thread_id = sys.argv[2] if len(sys.argv) > 2 else str(uuid.uuid4())
    run_async(ask(question, thread_id))


if __name__ == "__main__":
    main()
