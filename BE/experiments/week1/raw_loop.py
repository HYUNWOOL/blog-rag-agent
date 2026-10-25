"""프레임워크 없는 에이전트: Anthropic SDK + 툴 2개. 다음에 할 일(툴/종료)은 LLM이 정한다.

실행: uv run python experiments/week1/raw_loop.py "질문"
"""

import sys

import anthropic
import psycopg
from pgvector.psycopg import register_vector

from blog_rag_agent.agent_tools import (
    GET_POST_DESC,
    MAX_TOKENS,
    MODEL,
    SEARCH_POSTS_DESC,
    SYSTEM_PROMPT,
    run_get_post,
    run_search_posts,
)
from blog_rag_agent.config import load_settings
from blog_rag_agent.embedding import LocalEmbedder

MAX_STEPS = 6  # LLM 호출 상한. 넘으면 실패로 멈춘다(1주차 결정).

TOOLS = [
    {
        "name": "search_posts",
        "description": SEARCH_POSTS_DESC,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "검색어"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_post",
        "description": GET_POST_DESC,
        "input_schema": {
            "type": "object",
            "properties": {"post_id": {"type": "integer"}},
            "required": ["post_id"],
        },
    },
]


def run_raw(question, *, conn, embedder, client, log=print) -> dict:
    tools = {
        "search_posts": lambda i: run_search_posts(conn, embedder, i["query"]),
        "get_post": lambda i: run_get_post(conn, i["post_id"]),
    }
    messages = [{"role": "user", "content": question}]
    tokens_in = tokens_out = 0
    for step in range(1, MAX_STEPS + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        tokens_in += response.usage.input_tokens
        tokens_out += response.usage.output_tokens
        # content를 통째로 넣는다. tool_use 블록이 남아야 다음 tool_result와 짝이 맞는다.
        messages.append({"role": "assistant", "content": response.content})
        calls = [b for b in response.content if b.type == "tool_use"]
        log(
            f"[step {step}] stop_reason={response.stop_reason} "
            f"in={response.usage.input_tokens} out={response.usage.output_tokens} "
            f"tools={[(b.name, b.input) for b in calls]} messages={len(messages)}"
        )
        if response.stop_reason != "tool_use":
            return {
                "answer": "".join(b.text for b in response.content if b.type == "text"),
                "llm_calls": step,
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "messages": messages,
            }
        # 이번 응답의 모든 tool_use 결과를 user 메시지 하나에 모아 보낸다.
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": tools[b.name](b.input),
                    }
                    for b in calls
                ],
            }
        )
        log(f"         tool_result {len(calls)}개 추가 messages={len(messages)}")
    raise RuntimeError(f"max_steps={MAX_STEPS}에 닿았다. 답 없이 멈춘다.")


def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else "스위스에서 배를 탄 이유가 뭐야?"
    settings = load_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        register_vector(conn)
        result = run_raw(
            question,
            conn=conn,
            embedder=LocalEmbedder(settings.embedding_model),
            client=anthropic.Anthropic(api_key=settings.anthropic_api_key),
        )
    print(f"\n답({result['llm_calls']}회 호출):\n{result['answer']}")


if __name__ == "__main__":
    main()
