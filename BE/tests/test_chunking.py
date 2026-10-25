from blog_rag_agent.ingest.chunking import MAX_CHARS, chunk_post


def test_splits_by_heading_and_keeps_image_alt_only():
    body = (
        "## 첫째\n\n![밴프 곤돌라](https://x/1.jpg)\n\n"
        + "가" * 250
        + "\n\n## 둘째\n\n"
        + "나" * 250
    )
    chunks = chunk_post("밴프", body)

    assert [c.heading for c in chunks] == ["첫째", "둘째"]
    assert chunks[0].text.startswith("밴프 > 첫째\n\n밴프 곤돌라")
    assert "https://" not in chunks[0].text


def test_short_section_is_merged_and_heading_kept_as_text():
    chunks = chunk_post("t", "## 짧음\n\n짧은 글\n\n## 긴 섹션\n\n" + "가" * 300)
    assert len(chunks) == 1
    assert "## 긴 섹션" in chunks[0].text


def test_code_block_is_never_split_even_if_long():
    code = "```python\n" + "\n\n".join(f"x{i} = {i}" for i in range(400)) + "\n```"
    body = "## 코드\n\n" + "가" * 300 + "\n\n" + code
    chunks = chunk_post("t", body)

    assert len(code) > MAX_CHARS
    # 빈 줄이 있어도 코드 블록이 한 덩어리로 남는다
    assert any(code in c.text for c in chunks)
