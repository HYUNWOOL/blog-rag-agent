"""웹 서버: 세션, 만료, 하루 한도, healthz, 답변 스트림. 그래프는 가짜로 바꿔 LLM을 부르지 않는다."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk

from blog_rag_agent.api.app import create_app
from blog_rag_agent.api.security import SESSION_COOKIE, hash_code
from blog_rag_agent.api.settings import ApiSettings, cost_usd
from blog_rag_agent.api.stream import AnswerExtractor

PEPPER = b"p" * 32
CODE = "test-code-123"


class FakeGraph:
    """answer 노드가 JSON을 조각으로 내보내는 척한다. 사이에 grade 토큰을 섞어 걸러지는지 본다."""

    def __init__(self, answer_json: str = "", source_post_ids=(), calls=None) -> None:
        self.answer_json = answer_json
        self.source_post_ids = list(source_post_ids)
        self.calls = calls if calls is not None else []

    async def astream(self, inputs, config, stream_mode):
        self.calls.append(inputs["question"])
        yield AIMessageChunk(content='{"sufficient": true'), {"langgraph_node": "grade"}
        for i in range(0, len(self.answer_json), 3):
            yield AIMessageChunk(content=self.answer_json[i : i + 3]), {"langgraph_node": "answer"}

    async def aget_state(self, config):
        values = {
            "status": "answered",
            "answer": json.loads(self.answer_json)["answer"],
            "source_post_ids": self.source_post_ids,
            "turn": 1,
        }
        return SimpleNamespace(values=values)


def settings(test_db_url) -> ApiSettings:
    return ApiSettings(
        database_url=test_db_url,
        anthropic_api_key="unused",
        embedding_model="unused",
        access_code_pepper=PEPPER,
        session_secret=b"s" * 32,
        daily_question_limit=20,
        answer_max_tokens=256,
        chat_model="claude-haiku-5-5",
    )


def client_for(test_db_url, graph) -> TestClient:
    @asynccontextmanager
    async def factory(_settings, _checkpointer):
        yield graph

    app = create_app(settings(test_db_url), graph_factory=factory)
    # https: Secure 쿠키를 테스트 클라이언트가 다시 보내게 한다. 셀렉터 루프: Windows psycopg 비동기.
    return TestClient(
        app,
        base_url="https://testserver",
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    )


def add_code(db, *, expires_in=timedelta(days=1), limit=20) -> int:
    (code_id,) = db.execute(
        "INSERT INTO access_codes (code_hash, company, expires_at, daily_question_limit)"
        " VALUES (%s, '테스트사', %s, %s) RETURNING id",
        (hash_code(PEPPER, CODE), datetime.now(UTC) + expires_in, limit),
    ).fetchone()
    return code_id


def events(body: str) -> list[tuple[str, object]]:
    out = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((fields["event"], json.loads(fields["data"])))
    return out


def test_chat_without_session_is_401(db, test_db_url):
    with client_for(test_db_url, FakeGraph()) as client:
        assert client.post("/api/chat", json={"question": "안녕"}).status_code == 401


def test_tampered_session_cookie_is_401(db, test_db_url):
    add_code(db)
    with client_for(test_db_url, FakeGraph()) as client:
        assert client.post("/api/session", json={"code": CODE}).status_code == 204
        code_id, rest = client.cookies[SESSION_COOKIE].split(":", 1)
        forged = f"{int(code_id) + 1}:{rest}"  # 서명은 그대로 두고 코드 id만 바꾼다
        client.cookies.clear()
        client.cookies.set(SESSION_COOKIE, forged)
        assert client.post("/api/chat", json={"question": "안녕"}).status_code == 401


def test_session_cookie_flags_and_wrong_code(db, test_db_url):
    add_code(db)
    with client_for(test_db_url, FakeGraph()) as client:
        assert client.post("/api/session", json={"code": "wrong"}).status_code == 401
        response = client.post("/api/session", json={"code": CODE})
    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    for flag in ("httponly", "secure", "samesite=lax", "max-age=7200"):
        assert flag in cookie


def test_expired_code_is_rejected(db, test_db_url):
    add_code(db, expires_in=timedelta(seconds=-1))
    with client_for(test_db_url, FakeGraph()) as client:
        assert client.post("/api/session", json={"code": CODE}).status_code == 401


def test_code_expiring_after_login_is_rejected_on_chat(db, test_db_url):
    code_id = add_code(db)
    calls = []
    with client_for(test_db_url, FakeGraph(calls=calls)) as client:
        assert client.post("/api/session", json={"code": CODE}).status_code == 204
        db.execute(
            "UPDATE access_codes SET expires_at = now() - interval '1 second' WHERE id = %s",
            (code_id,),
        )
        assert client.post("/api/chat", json={"question": "안녕"}).status_code == 401
    assert calls == []


def test_over_daily_limit_is_429_and_graph_not_called(db, test_db_url):
    code_id = add_code(db, limit=2)
    for _ in range(2):
        db.execute("INSERT INTO usage_log (code_id, thread_id) VALUES (%s, 't')", (code_id,))
    calls = []
    with client_for(test_db_url, FakeGraph(calls=calls)) as client:
        assert client.post("/api/session", json={"code": CODE}).status_code == 204
        assert client.post("/api/chat", json={"question": "안녕"}).status_code == 429
    assert calls == []
    assert db.execute("SELECT count(*) FROM usage_log").fetchone() == (2,)


def test_yesterdays_usage_does_not_count(db, test_db_url):
    code_id = add_code(db, limit=1)
    db.execute(
        "INSERT INTO usage_log (code_id, thread_id, created_at)"
        " VALUES (%s, 't', now() - interval '1 day')",
        (code_id,),
    )
    answer = json.dumps({"answer": "네", "source_post_ids": []}, ensure_ascii=False)
    with client_for(test_db_url, FakeGraph(answer)) as client:
        client.post("/api/session", json={"code": CODE})
        assert client.post("/api/chat", json={"question": "안녕"}).status_code == 200


def test_healthz_checks_db(db, test_db_url):
    with client_for(test_db_url, FakeGraph()) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_streams_answer_tokens_then_sources_and_records_usage(db, test_db_url):
    code_id = add_code(db)
    (post_id,) = db.execute(
        "INSERT INTO posts (url, title, published_at, updated_at, content_hash, body)"
        " VALUES ('https://example.com/a/', '글 A', now(), now(), 'h', 'b') RETURNING id"
    ).fetchone()
    answer_text = '카파도키아 → "안탈리아"\n다음 줄 😀'
    answer = json.dumps({"answer": answer_text, "source_post_ids": [post_id]})
    with client_for(test_db_url, FakeGraph(answer, [post_id])) as client:
        client.post("/api/session", json={"code": CODE})
        response = client.post("/api/chat", json={"question": "순서?"})
    assert response.status_code == 200
    got = events(response.text)
    tokens = [data["text"] for name, data in got if name == "token"]
    assert len(tokens) > 1  # 한 번에 오지 않고 나뉘어 온다
    assert "".join(tokens) == answer_text  # grade 토큰과 JSON 껍데기가 섞이지 않는다
    assert got[-1] == ("sources", [{"title": "글 A", "url": "https://example.com/a/"}])
    row = db.execute(
        "SELECT status, turn, input_tokens, cost_usd, finished_at IS NOT NULL"
        " FROM usage_log WHERE code_id = %s",
        (code_id,),
    ).fetchone()
    assert row == ("done", 1, 0, Decimal("0.000000"), True)


@pytest.mark.parametrize("size", [1, 2, 5, 1000])
def test_answer_extractor_decodes_split_escapes(size):
    text = 'a"b\\c\n탭\té 😀 끝'
    raw = json.dumps({"answer": text, "source_post_ids": [1, 2]})  # ensure_ascii로 \uXXXX 이스케이프
    extractor = AnswerExtractor()
    out = "".join(extractor.feed(raw[i : i + size]) for i in range(0, len(raw), size))
    assert out == text


def test_cost_is_decimal_per_million_tokens():
    assert cost_usd("claude-haiku-5-5", 1_000_000, 0) == Decimal("0.100000")
    assert cost_usd("claude-haiku-5-5", 3_000, 500) == Decimal("0.000550")
