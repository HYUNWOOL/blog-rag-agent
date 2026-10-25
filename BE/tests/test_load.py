import psycopg
import pytest
from fakes import FakeEmbedder

from blog_rag_agent.embedding import EMBEDDING_DIM
from blog_rag_agent.ingest.collect import render_file
from blog_rag_agent.ingest.load import load_dir, load_post, parse_post_file
from blog_rag_agent.retrieval.search import get_post, search

BODY = "## 첫째 날\n\n" + "가" * 300 + "\n\n## 둘째 날\n\n" + "나" * 300 + "\n"


def write_post(posts_dir, slug: str, body: str):
    # 실제 수집 파일과 같은 형식으로 쓰도록 collect.render_file을 그대로 쓴다.
    post = {
        "link": f"https://example.com/{slug}/",
        "title": {"rendered": f"{slug} 여행"},
        "date_gmt": "2026-01-01T00:00:00",
        "modified_gmt": "2026-01-02T00:00:00",
    }
    path = posts_dir / f"{slug}.md"
    path.write_text(render_file(post, ["유럽"], body), encoding="utf-8", newline="\n")
    return path


def counts(db):
    return db.execute(
        "SELECT (SELECT count(*) FROM posts), (SELECT count(*) FROM chunks)"
    ).fetchone()


def chunk_rows(db, url):
    return db.execute(
        "SELECT c.id, c.text FROM chunks c JOIN posts p ON p.id = c.post_id"
        " WHERE p.url = %s ORDER BY c.chunk_index",
        (url,),
    ).fetchall()


def test_loading_twice_keeps_row_counts(db, tmp_path):
    write_post(tmp_path, "bergen", BODY)
    write_post(tmp_path, "malaga", BODY.replace("가", "다"))
    embedder = FakeEmbedder(dim=EMBEDDING_DIM)

    first = load_dir(db, tmp_path, embedder)
    rows_after_first = counts(db)
    second = load_dir(db, tmp_path, embedder)

    assert first[0] == {"embedded": 2} and second[0] == {"unchanged": 2}
    assert counts(db) == rows_after_first == (2, 4)
    assert embedder.calls == 2  # 두 번째 적재에서는 임베딩을 부르지 않았다


def test_only_changed_post_is_reembedded(db, tmp_path):
    write_post(tmp_path, "bergen", BODY)
    write_post(tmp_path, "malaga", BODY.replace("가", "다"))
    embedder = FakeEmbedder(dim=EMBEDDING_DIM)
    load_dir(db, tmp_path, embedder)
    bergen_before = chunk_rows(db, "https://example.com/bergen/")

    write_post(tmp_path, "malaga", BODY.replace("가", "라"))
    counts_by_result, _ = load_dir(db, tmp_path, embedder)

    assert counts_by_result == {"unchanged": 1, "embedded": 1}
    assert embedder.calls == 3
    assert "라" * 300 in embedder.texts[-2]  # 세 번째 호출로 들어온 건 바뀐 글의 청크
    # 안 바뀐 글은 청크 id까지 그대로다(지웠다 다시 넣지 않았다)
    assert chunk_rows(db, "https://example.com/bergen/") == bergen_before


def test_failed_replace_keeps_previous_chunks(db, tmp_path):
    path = write_post(tmp_path, "bergen", BODY)
    load_dir(db, tmp_path, FakeEmbedder(dim=EMBEDDING_DIM))
    before = chunk_rows(db, "https://example.com/bergen/")
    hash_before = db.execute("SELECT content_hash FROM posts").fetchone()

    write_post(tmp_path, "bergen", BODY.replace("가", "마"))
    # 차원이 틀린 벡터는 DELETE 뒤 INSERT에서 실패한다. 즉 "교체 중" 예외다.
    with pytest.raises(psycopg.Error):
        load_post(db, parse_post_file(path), FakeEmbedder(dim=3))

    assert chunk_rows(db, "https://example.com/bergen/") == before
    assert db.execute("SELECT content_hash FROM posts").fetchone() == hash_before


def test_search_and_get_post(db, tmp_path):
    write_post(tmp_path, "bergen", BODY)
    embedder = FakeEmbedder(dim=EMBEDDING_DIM)
    load_dir(db, tmp_path, embedder)
    chunk_text = chunk_rows(db, "https://example.com/bergen/")[1][1]

    # 가짜 임베더는 같은 텍스트에 같은 벡터를 주므로, 청크 텍스트로 검색하면 그 청크가 거리 0으로 1등이다.
    hits = search(db, embedder, chunk_text, k=2)
    post = get_post(db, hits[0]["post_id"])

    assert hits[0]["text"] == chunk_text
    assert hits[0]["distance"] == pytest.approx(0, abs=1e-6)
    assert len(hits) == 2
    assert post["url"] == "https://example.com/bergen/" and post["body"] == BODY
    assert get_post(db, 999_999) is None
