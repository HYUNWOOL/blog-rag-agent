"""마크다운 본문을 `##` 소제목 단위 청크로 나눈다(1주차 결정, notes/decisions.md)."""

import re
from dataclasses import dataclass

# 소제목 하나가 이보다 짧으면 다음 섹션과 합친다. 너무 짧은 청크는 임베딩이 맥락을 잃는다.
MIN_CHARS = 200
# 섹션이 이보다 길면 문단 경계에서 나눈다. 블로그 섹션 평균은 약 400자라 드물게만 걸린다.
MAX_CHARS = 1500
IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")


@dataclass(frozen=True)
class Chunk:
    heading: str | None
    text: str


def _blocks(body: str) -> list[str]:
    """빈 줄로 문단을 나누되, ``` 코드 블록 안의 빈 줄에서는 나누지 않는다."""
    blocks: list[str] = []
    current: list[str] = []
    in_code = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if not line.strip() and not in_code:
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _sections(body: str) -> list[tuple[str | None, list[str]]]:
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for block in _blocks(body):
        if block.startswith("```"):
            # 코드 블록은 그대로 둔다(이미지 치환도 안 함)
            sections[-1][1].append(block)
            continue
        if block.startswith("## "):
            heading, _, rest = block.partition("\n")
            sections.append((heading[3:].strip(), []))
            block = rest
        # 이미지 URL은 검색에 쓸모가 없고, alt에는 장소 설명이 있어 alt만 남긴다.
        block = IMAGE.sub(r"\1", block).strip()
        if block:
            sections[-1][1].append(block)
    return [s for s in sections if s[1]]


def _size(blocks: list[str]) -> int:
    return sum(len(b) for b in blocks)


def chunk_post(title: str, body: str) -> list[Chunk]:
    merged: list[tuple[str | None, list[str]]] = []
    for heading, blocks in _sections(body):
        if merged and _size(merged[-1][1]) < MIN_CHARS:
            # 앞 섹션이 짧으면 이번 섹션을 앞에 붙인다. 소제목은 본문 줄로 남겨 정보를 잃지 않는다.
            prev_heading, prev_blocks = merged[-1]
            label = [f"## {heading}"] if heading else []
            merged[-1] = (prev_heading, prev_blocks + label + blocks)
        else:
            merged.append((heading, blocks))
    if len(merged) > 1 and _size(merged[-1][1]) < MIN_CHARS:
        heading, blocks = merged.pop()
        label = [f"## {heading}"] if heading else []
        merged[-1] = (merged[-1][0], merged[-1][1] + label + blocks)

    chunks: list[Chunk] = []
    for heading, blocks in merged:
        # 검색된 청크만 봐도 어느 글의 어느 부분인지 알 수 있게 앞에 붙인다.
        prefix = f"{title} > {heading}" if heading else title
        part: list[str] = []
        for block in blocks:
            # 문단 하나가 MAX_CHARS보다 길어도 자르지 않는다(코드 블록 보호).
            if part and _size(part) + len(block) > MAX_CHARS:
                chunks.append(Chunk(heading, "\n\n".join([prefix, *part])))
                part = []
            part.append(block)
        if part:
            chunks.append(Chunk(heading, "\n\n".join([prefix, *part])))
    return chunks
