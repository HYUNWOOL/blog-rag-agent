"""워크플로우 v0: 질문 → search → 답변. 다음에 할 일은 전부 코드가 정한다(LLM 호출 1번)."""

import anthropic
import psycopg

from blog_rag_agent.agent_tools import (
    MAX_TOKENS,
    MODEL,
    SEARCH_K,
    SYSTEM_PROMPT,
    format_context,
)
from blog_rag_agent.retrieval.search import search


def answer_v0(
    question: str, *, conn: psycopg.Connection, embedder, client: anthropic.Anthropic
) -> dict:
    hits = search(conn, embedder, question, SEARCH_K)
    context = format_context(hits)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        output_config={"effort": "low"},
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"블로그 검색 결과:\n\n{context}\n\n질문: {question}",
            }
        ],
    )
    return {
        "answer": "".join(b.text for b in response.content if b.type == "text"),
        "llm_calls": 1,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
