import math

from fakes import FakeEmbedder


def test_fake_embedder_is_deterministic_and_counts_calls():
    embedder = FakeEmbedder(dim=16)
    first = embedder.embed(["스위스", "노르웨이"])
    second = embedder.embed(["스위스"])

    assert first[0] == second[0]  # 같은 텍스트 → 같은 벡터
    assert first[0] != first[1]
    assert len(first[0]) == 16
    assert math.isclose(sum(x * x for x in first[0]), 1.0)  # 단위 벡터
    assert embedder.calls == 2
    assert embedder.texts == ["스위스", "노르웨이", "스위스"]


def test_db_fixture_connects_to_migrated_test_db(db):
    assert db.info.dbname == "rag_test"
    assert db.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
    assert db.execute("SELECT version_num FROM alembic_version").fetchone()
