import asyncio

import pytest
from fakes import FakeEmbedder
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import NodeTimeoutError

from blog_rag_agent.db.question_log import upsert_question_log
from blog_rag_agent.embedding import EMBEDDING_DIM
from blog_rag_agent.graph import agentic
from blog_rag_agent.graph.agentic import (
    MAX_RETRIES,
    Answer,
    Verdict,
    build_graph,
    is_transient,
    merge_chunks,
    run_async,
    run_config,
)

ENOUGH = Verdict(sufficient=True)
LACKING = Verdict(sufficient=False, missing="이동 순서")


class Scripted:
    """정해 둔 값을 순서대로 돌려준다. 예외면 던지고, 함수면 기다렸다 돌려준다."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        step = self.script.pop(0)
        if callable(step):
            return await step()
        if isinstance(step, Exception):
            raise step
        return step


class FixedAnswer:
    def __init__(self, sources: list[int]) -> None:
        self.sources = sources

    async def ainvoke(self, messages):
        return Answer(answer="답변", source_post_ids=self.sources)


class FakeModel:
    def __init__(self, grades: list, sources: list[int] | None = None) -> None:
        self.grader = Scripted(grades)
        self.answerer = FixedAnswer([10] if sources is None else sources)
        self.rewrites = 0

    def with_structured_output(self, schema, method):
        return self.grader if schema is Verdict else self.answerer

    async def ainvoke(self, messages):
        if messages[0].content == agentic.FOLLOWUP_PROMPT:
            return AIMessage("후속검색어")
        self.rewrites += 1
        return AIMessage(f"재검색어{self.rewrites}")


def hit(chunk_id: int, post_id: int) -> dict:
    return {
        "chunk_id": chunk_id,
        "post_id": post_id,
        "title": f"글{post_id}",
        "url": f"https://example.com/{post_id}/",
        "heading": None,
        "text": "본문",
        "distance": 0.1,
    }


@pytest.fixture
def fake_search(monkeypatch):
    """검색어마다 다른 청크를 돌려주고, 받은 검색어를 기록한다."""
    queries: list[str] = []

    def search(conn, embedder, query, k):
        queries.append(query)
        return [hit(len(queries), len(queries) * 10)]

    monkeypatch.setattr(agentic, "search", search)
    return queries


def make_graph(db, model):
    embedder = FakeEmbedder(dim=EMBEDDING_DIM)
    return build_graph(db, embedder, model, InMemorySaver())


def ask(graph, question="질문"):
    return run_async(graph.ainvoke({"question": question}, run_config("t1")))


def run(db, model):
    return ask(make_graph(db, model))


def log_rows(db):
    return db.execute(
        "SELECT turn, status, attempts, llm_calls, source_post_ids FROM question_logs"
        " WHERE thread_id = 't1' ORDER BY turn"
    ).fetchall()


def test_sufficient_first_search_is_one_search_two_llm_calls(db, fake_search):
    state = run(db, FakeModel([ENOUGH]))

    assert state["answer"] == "답변"
    assert fake_search == ["질문"]
    assert log_rows(db) == [(1, "answered", 0, 2, [10])]


def test_retry_searches_with_rewritten_query_and_keeps_earlier_chunks(db, fake_search):
    state = run(db, FakeModel([LACKING, ENOUGH], sources=[10, 20]))

    assert fake_search == ["질문", "재검색어1"]
    assert [c["chunk_id"] for c in state["chunks"]] == [1, 2]
    assert log_rows(db) == [(1, "answered", 1, 4, [10, 20])]


def test_retry_cap_reaches_insufficient_within_recursion_limit(db, fake_search):
    model = FakeModel([LACKING] * (MAX_RETRIES + 1))

    state = run(db, model)

    assert len(fake_search) == MAX_RETRIES + 1
    assert "이동 순서" in state["answer"] and "글10" in state["answer"]
    # 판정 3번 + 재검색어 2번. insufficient는 LLM을 부르지 않고 근거 글도 없다.
    assert log_rows(db) == [(1, "insufficient", 2, 5, [])]


def test_answer_keeps_only_cited_posts_that_were_retrieved(db, fake_search):
    state = run(db, FakeModel([LACKING, ENOUGH], sources=[20, 999, 20]))

    assert state["source_post_ids"] == [20]
    assert log_rows(db)[0][4] == [20]


def test_second_turn_rewrites_first_and_starts_clean(db, fake_search):
    graph = make_graph(db, FakeModel([ENOUGH, ENOUGH], sources=[10, 20]))

    ask(graph)
    state = ask(graph, "거기 입장료는?")

    assert fake_search == ["질문", "후속검색어"]
    assert state["turn"] == 2 and state["attempts"] == 0
    assert [c["chunk_id"] for c in state["chunks"]] == [2]
    assert [t["question"] for t in state["history"]] == ["질문", "거기 입장료는?"]
    # 후속 턴의 근거에 지난 턴의 글(10)이 섞이지 않는다.
    assert log_rows(db) == [(1, "answered", 0, 2, [10]), (2, "answered", 0, 3, [20])]


def test_upsert_on_same_thread_and_turn_leaves_one_row(db):
    row = {
        "thread_id": "t1",
        "turn": 1,
        "question": "질문",
        "answer": "답변",
        "attempts": 0,
        "llm_calls": 2,
        "source_post_ids": [10],
    }

    upsert_question_log(db, status="insufficient", **row)
    upsert_question_log(db, status="answered", **row)

    assert log_rows(db) == [(1, "answered", 0, 2, [10])]


def test_search_outage_reaches_insufficient_after_retries(db, monkeypatch):
    calls = []

    def search(conn, embedder, query, k):
        calls.append(query)
        raise ConnectionError("끊김")

    monkeypatch.setattr(agentic, "search", search)
    model = FakeModel([ENOUGH])

    state = run(db, model)

    assert len(calls) == 3 and model.grader.calls == 0
    assert "검색 오류" in state["answer"]
    assert log_rows(db) == [(1, "insufficient", 0, 0, [])]


def test_search_bug_is_raised_not_hidden(db, monkeypatch):
    def search(conn, embedder, query, k):
        raise ValueError("버그")

    monkeypatch.setattr(agentic, "search", search)

    with pytest.raises(ValueError):
        run(db, FakeModel([ENOUGH]))

    assert log_rows(db) == []


def test_transient_error_is_retried_inside_the_node(db, fake_search):
    model = FakeModel([ConnectionError("끊김"), ENOUGH])

    state = run(db, model)

    assert state["answer"] == "답변" and model.grader.calls == 2


def test_permanent_error_stops_without_retry_or_log(db, fake_search):
    model = FakeModel([ValueError("버그"), ENOUGH])

    with pytest.raises(ValueError):
        run(db, model)

    assert model.grader.calls == 1 and log_rows(db) == []


def test_node_timeout_is_retried_then_raised(db, fake_search, monkeypatch):
    monkeypatch.setattr(agentic, "LLM_TIMEOUT_SECONDS", 0.05)

    async def hang():
        await asyncio.sleep(5)

    model = FakeModel([hang] * 3)

    with pytest.raises(NodeTimeoutError):
        run(db, model)

    assert model.grader.calls == 3 and log_rows(db) == []


def test_merge_chunks_drops_duplicates_by_chunk_id():
    assert merge_chunks([hit(1, 10)], [hit(1, 10), hit(2, 10)]) == [
        hit(1, 10),
        hit(2, 10),
    ]


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (TimeoutError(), True),
        (ConnectionError(), True),
        (ValueError(), False),
        (type("Auth", (Exception,), {"is_retryable": False})(), False),
    ],
)
def test_is_transient(exc, expected):
    assert is_transient(exc) is expected
